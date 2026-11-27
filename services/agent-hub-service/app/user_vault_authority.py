"""Fetch and verify the current User vault for a transferred Hub account."""

import hashlib
import os
import re
import time
from dataclasses import dataclass
from uuid import uuid4

import httpx

from folioview_shared.delegation import PRIVATE_AUTHORITY_DELEGATION_TYPE
from folioview_shared.encrypted.authority import verify_registry
from folioview_shared.encrypted.constants import CONTRACT_VERSION, MAX_READ_BYTES
from folioview_shared.encrypted.crypto import signing_input_fingerprint
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json, strict_json_loads
from folioview_shared.encrypted.private_resources import (
    PRIVATE_AUTHORITY_PROFILE,
    PrivateRegistryCursor,
    private_authority_lookup,
    source_index_digest,
    verify_private_registry_transition,
)
from folioview_shared.identity import owner_key

from .catalogue import _JWT, bounded_bytes, remaining, workload_token
from .private_authority import numbered_user_origin
from .signing import _EMAIL, get_signer, origin
from .store import private_resource_writer_fence_path

HUB_AUTHORITY_PATH = "/internal/v2/private-resources/hub-authority/read"
ARCHIVE_RETIREMENT_PATH = "/internal/v2/private-resources/hub-archive-retirement/read"
_AUTHORITY_FIELDS = {
    "ownerSubject",
    "vaultId",
    "rootKeyId",
    "rootJwk",
    "vaultVersion",
    "registry",
    "registryStart",
    "archive",
    "signedTransition",
    "sourcesDigest",
    "registryHistory",
    "sources",
}
_OWNER = re.compile(r"[a-f0-9]{64}\Z")


@dataclass(frozen=True)
class CurrentUserVault:
    authority: dict
    cursor: PrivateRegistryCursor
    writer_fence: dict
    expires_at: float
    retirement: dict | None = None

    def require_active_holdings(self, bindings):
        active = {
            canonical_json(row["binding"])
            for row in self.authority["sources"]
            if row["state"] == "active"
        }
        if any(
            binding["ref"]["kind"] == "holdings" and canonical_json(binding) not in active
            for binding in bindings
        ):
            raise ContractError("version_conflict")

    def require_current(self, unit, now):
        owner = self.authority["ownerSubject"]
        if (
            now >= self.expires_at
            or unit.get(private_resource_writer_fence_path(owner)) != self.writer_fence
        ):
            raise ContractError("source_unavailable")


class UserVaultAuthority:
    def __init__(
        self,
        *,
        issuer,
        caller,
        user_origin,
        signer_factory=get_signer,
        token_factory=workload_token,
        transport=None,
        clock=time.monotonic,
        wall_clock=time.time,
    ):
        self.issuer, self.caller, self.user_origin = issuer, caller, user_origin
        self.signer_factory, self.token_factory = signer_factory, token_factory
        self.transport, self.clock, self.wall_clock = transport, clock, wall_clock

    def read(self, uid, vault, writer_fence, *, minimum_epoch=2, deadline=None, retirement=False):
        owner = owner_key(uid)
        if (
            type(writer_fence) is not dict
            or writer_fence.get("ownerSubject") != owner
            or writer_fence.get("vaultId") != vault
            or writer_fence.get("state") != "transferred"
            or type(writer_fence.get("writerEpoch")) is not int
            or writer_fence["writerEpoch"] != 2
            or type(writer_fence.get("rootKeyId")) is not str
            or type(writer_fence.get("transitionFingerprint")) is not str
        ):
            raise ContractError("source_unavailable")
        lookup = private_authority_lookup(
            {
                "contractVersion": CONTRACT_VERSION,
                "profile": PRIVATE_AUTHORITY_PROFILE,
                "consumer": "hub",
                "ownerSubject": owner,
                "vaultId": vault,
                "sourceId": None,
                "minimumRegistryEpoch": minimum_epoch,
                "nonce": uuid4().hex,
            }
        )
        try:
            started_at = self.wall_clock()
            window = self.clock() + 8
            deadline = window if deadline is None else min(window, deadline)
            remaining(deadline, self.clock)
            raw = canonical_json(lookup)
            request_digest = hashlib.sha256(raw).hexdigest()
            path = ARCHIVE_RETIREMENT_PATH if retirement else HUB_AUTHORITY_PATH
            response = self._fetch(
                uid, lookup["nonce"], raw, request_digest, started_at, deadline, path
            )
            expected = {
                key: lookup[key] for key in ("contractVersion", "profile", "consumer", "nonce")
            }
            expected["requestDigest"] = request_digest
            if (
                type(response) is not dict
                or set(response)
                != (
                    {*expected, "authority", "retirement"}
                    if retirement
                    else {*expected, "authority"}
                )
                or any(response[key] != value for key, value in expected.items())
            ):
                raise ContractError("recipient_binding_mismatch")
            verified = self._verify(
                response["authority"], lookup, writer_fence, int(self.wall_clock())
            )
            remaining(deadline, self.clock)
            return CurrentUserVault(
                response["authority"],
                verified,
                dict(writer_fence),
                started_at + 8,
                response.get("retirement"),
            )
        except (ContractError, httpx.HTTPError, TypeError, ValueError, OverflowError):
            raise ContractError("source_unavailable") from None

    def _fetch(self, uid, nonce, raw, request_digest, started_at, deadline, path):
        issuer = origin(self.issuer)
        user_origin = numbered_user_origin(issuer, self.user_origin)
        if _EMAIL.fullmatch(self.caller) is None:
            raise ContractError("authorization_unavailable")
        now = int(started_at)
        url = user_origin + path
        workload = self.token_factory(user_origin, deadline=deadline, clock=self.clock)
        delegation = self.signer_factory().sign(
            {
                "iss": issuer,
                "aud": url,
                "sub": uid,
                "iat": now,
                "exp": now + 60,
                "jti": nonce,
                "caller": self.caller,
                "purpose": "private_authority_read",
                "requestDigest": request_digest,
            },
            typ=PRIVATE_AUTHORITY_DELEGATION_TYPE,
            deadline=deadline,
            budget_clock=self.clock,
        )
        if any(
            type(token) is not str or len(token) > 16_384 or _JWT.fullmatch(token) is None
            for token in (workload, delegation)
        ):
            raise ContractError("invalid_token")
        with httpx.Client(
            trust_env=False, follow_redirects=False, transport=self.transport
        ) as client:
            with client.stream(
                "POST",
                url,
                headers={
                    "Authorization": f"Bearer {workload}",
                    "X-FolioView-Delegation": delegation,
                    "X-FolioView-Contract": CONTRACT_VERSION,
                    "Content-Type": "application/json",
                    "Cache-Control": "no-store",
                    "Accept-Encoding": "identity",
                },
                content=raw,
                timeout=remaining(deadline, self.clock),
            ) as response:
                if (
                    response.status_code != 200
                    or response.headers.get("content-type", "").split(";", 1)[0].lower()
                    != "application/json"
                    or response.headers.get("x-folioview-contract") != CONTRACT_VERSION
                ):
                    raise ContractError("source_unavailable")
                return strict_json_loads(
                    bounded_bytes(response, deadline, self.clock, maximum=MAX_READ_BYTES),
                    max_bytes=MAX_READ_BYTES,
                )

    def _verify(self, value, lookup, fence, now):
        if (
            type(value) is not dict
            or value.keys() != _AUTHORITY_FIELDS
            or any(value[key] != lookup[key] for key in ("ownerSubject", "vaultId"))
            or value["rootKeyId"] != fence["rootKeyId"]
            or type(value["vaultVersion"]) is not int
            or value["vaultVersion"] < 2
            or type(value["registryHistory"]) is not list
            or not 1 <= len(value["registryHistory"]) <= 129
            or type(value["registry"]) is not dict
            or type(value["registry"].get("registryEpoch")) is not int
            or value["registry"]["registryEpoch"] < lookup["minimumRegistryEpoch"]
            or source_index_digest(value["sources"]) != value["sourcesDigest"]
        ):
            raise ContractError("recipient_binding_mismatch")
        scope = {
            "owner_subject": value["ownerSubject"],
            "vault_id": value["vaultId"],
            "pinned_root_key_id": value["rootKeyId"],
            "root_jwk": value["rootJwk"],
            "now": now,
        }
        first, *later = value["registryHistory"]
        fingerprint = signing_input_fingerprint(value["signedTransition"])
        if fingerprint != fence["transitionFingerprint"]:
            raise ContractError("registry_conflict")
        start = verify_private_registry_transition(
            value["signedTransition"],
            first_bundle=first,
            authenticated_start=value["registryStart"],
            **scope,
        )
        registry = start.registry
        for bundle in later:
            following = verify_registry(bundle, previous=registry, **scope)
            if following.registry_sequence != registry.registry_sequence + 1:
                raise ContractError("registry_conflict")
            registry = following
        result = PrivateRegistryCursor(registry, start.registry_epoch)
        if result.head() != value["registry"]:
            raise ContractError("registry_conflict")
        return result


class ScopedUserVaults:
    """Resolve the selected account before a Hub transaction and check it again within one."""

    def __init__(self, store, *, owner=None, client=None):
        if owner is not None and (type(owner) is not str or _OWNER.fullmatch(owner) is None):
            raise ContractError("authorization_unavailable")
        self.store, self.owner, self.client = store, owner, client

    def read(self, uid, vault=None, *, deadline=None):
        owner = owner_key(uid)
        if owner != self.owner:
            return None
        fence_path = private_resource_writer_fence_path(owner)
        fence = self.store.read_snapshot(lambda: [fence_path], lambda unit: unit.get(fence_path))
        if fence is None:
            return None
        if self.client is None or type(fence) is not dict:
            raise ContractError("source_unavailable")
        selected_vault = vault if vault is not None else fence.get("vaultId")
        if type(selected_vault) is not str:
            raise ContractError("source_unavailable")
        if deadline is not None:
            return self.client.read(uid, selected_vault, fence, deadline=deadline)
        return self.client.read(uid, selected_vault, fence)


def scoped_user_vaults(store):
    if os.getenv("HUB_USER_VAULT_AUTHORITY_ENABLED") != "1":
        return ScopedUserVaults(store)
    owner = os.getenv("HUB_USER_PRIVATE_AUTHORITY_OWNER", "")
    return ScopedUserVaults(
        store,
        owner=owner,
        client=UserVaultAuthority(
            issuer=os.getenv("HUB_SERVICE_AUDIENCE", ""),
            caller=os.getenv("HUB_CATALOGUE_CALLER_EMAIL", ""),
            user_origin=os.getenv("HUB_USER_ORIGIN", ""),
        ),
    )
