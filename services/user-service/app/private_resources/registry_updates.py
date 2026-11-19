"""Advance the transferred registry as one verified, replayable User write."""

import time
from typing import Literal

from folioview_shared.encrypted.authority import verify_registry
from folioview_shared.encrypted.constants import CONTRACT_VERSION, MAX_READ_BYTES, MAX_SAFE_INTEGER
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json
from folioview_shared.encrypted.private_resources import PrivateRegistryCursor, source_index_digest
from folioview_shared.identity import owner_key

from ..resources import ResourceUnavailable, SQLiteUserResourceStore
from .authority_cutover import UserAuthorityCutover
from .authority_views import _recipient_keys
from .legacy_baselines import _sha
from .recovery import COLLECTION as HEADS
from .recovery import (
    ClosedModel,
    Digest,
    Identifier,
    OperationId,
    RegistryHead,
    Version,
    build_recovery_head,
)
from .registry_pages import COLLECTION as HISTORY
from .registry_pages import MAX_ENTRY_BYTES, _index
from .source_invalidations import SOURCE_INDEX
from .source_registrations import _MAX_REGISTRY_EXTENSION, _matches_current, current_registry

REGISTRY_UPDATE_PROFILE = "folioview.owner-registry-update.v1"
REGISTRY_MUTATIONS = "user_private_registry_mutations"


class RegistryUpdate(ClosedModel):
    contractVersion: Literal[CONTRACT_VERSION]
    profile: Literal[REGISTRY_UPDATE_PROFILE]
    ownerSubject: Digest
    vaultId: Identifier
    operationId: OperationId
    expectedVaultVersion: Version
    registryBundle: dict


class RegistryUpdateReceipt(ClosedModel):
    contractVersion: Literal[CONTRACT_VERSION]
    profile: Literal[REGISTRY_UPDATE_PROFILE]
    ownerSubject: Digest
    vaultId: Identifier
    operationId: OperationId
    requestDigest: Digest
    vaultVersion: Version
    registry: RegistryHead


class RegistryUpdates:
    def __init__(self, store, *, clock=time.time):
        self.authority = UserAuthorityCutover(store)
        self.clock = clock
        if isinstance(store, SQLiteUserResourceStore):
            with store.connection() as db:
                db.execute(
                    f"CREATE TABLE IF NOT EXISTS {REGISTRY_MUTATIONS} "
                    "(owner TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )

    def update(self, uid, value: RegistryUpdate):
        self.authority._named_store()
        owner, vault, operation = owner_key(uid), value.vaultId, value.operationId
        if value.ownerSubject != owner:
            raise ContractError("insufficient_scope")
        fingerprint = _sha(canonical_json(value.model_dump()))
        identity = (REGISTRY_MUTATIONS, _sha(canonical_json([owner, vault, operation])))

        def replay(previous):
            previous = RegistryUpdateReceipt.model_validate(previous).model_dump()
            if (
                previous.get("ownerSubject") != owner
                or previous.get("vaultId") != vault
                or previous.get("operationId") != operation
            ):
                raise ContractError("authorization_unavailable")
            if previous.get("requestDigest") != fingerprint:
                raise ContractError("idempotency_conflict")
            if previous["vaultVersion"] != value.expectedVaultVersion + 1:
                raise ContractError("authorization_unavailable")
            return previous

        try:
            previous = self.authority._read((identity,))[0]
            if previous is not None:
                return replay(previous)
            now = int(self.clock())
            sample, before, bundles = current_registry(self.authority, uid, vault, now)
            if (
                sample["vaultVersion"] != value.expectedVaultVersion
                or sample["vaultVersion"] >= MAX_SAFE_INTEGER
                or len(bundles) > _MAX_REGISTRY_EXTENSION
            ):
                raise ContractError("version_conflict")
            root = sample["rootJwk"]
            registry = verify_registry(
                value.registryBundle,
                root_jwk=root,
                pinned_root_key_id=sample["rootKeyId"],
                owner_subject=owner,
                vault_id=vault,
                now=now,
                previous=before,
            )
            if registry.registry_sequence != before.registry_sequence + 1:
                raise ContractError("registry_conflict")
            _recipient_keys(registry, now)
            if len(canonical_json([*bundles, value.registryBundle])) > MAX_READ_BYTES - 65_536:
                raise ContractError("payload_too_large")
            cursor = PrivateRegistryCursor(registry, sample["registry"]["registryEpoch"])
            updated_registry = cursor.head()
            indexed = (
                HISTORY,
                _index(owner, vault, cursor.registry_epoch, registry.registry_sequence),
            )
            entry = {"head": updated_registry, "bundle": value.registryBundle, "rootJwk": root}
            if len(canonical_json(entry)) > MAX_ENTRY_BYTES:
                raise ContractError("payload_too_large")
            current = (HEADS, owner)
            receipt = {
                "contractVersion": CONTRACT_VERSION,
                "profile": REGISTRY_UPDATE_PROFILE,
                "ownerSubject": owner,
                "vaultId": vault,
                "operationId": operation,
                "requestDigest": fingerprint,
                "vaultVersion": value.expectedVaultVersion + 1,
                "registry": updated_registry,
            }

            def commit(read, write):
                saved, head, sources, occupied = read(
                    (identity, current, (SOURCE_INDEX, owner), indexed)
                )
                if saved is not None:
                    return replay(saved)
                if occupied is not None or not _matches_current(head, sample):
                    raise ContractError("version_conflict")
                if (
                    type(sources) is not dict
                    or sources.get("ownerSubject") != owner
                    or sources.get("vaultId") != vault
                    or source_index_digest(sources.get("entries")) != head["sourcesDigest"]
                ):
                    raise ContractError("source_unavailable")
                projection = build_recovery_head(
                    cursor=cursor,
                    registry_start=head["registryStart"],
                    vault_version=receipt["vaultVersion"],
                    archive=head["archive"],
                    sources=sources["entries"],
                    now=now,
                )
                if not projection["devices"]:
                    raise ContractError("key_authorization_required")
                write(
                    {
                        identity: receipt,
                        current: {**projection, "handover": head["handover"]},
                        indexed: entry,
                    }
                )
                return receipt

            return self.authority._transaction(commit, writes=True, replace=(current,))
        except ContractError:
            raise
        except ResourceUnavailable as error:
            if isinstance(error.__cause__, ContractError):
                raise error.__cause__ from None
        except (TypeError, ValueError, OverflowError):
            pass
        raise ContractError("authorization_unavailable")
