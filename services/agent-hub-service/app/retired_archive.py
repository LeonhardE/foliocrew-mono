"""Dispose only of a frozen archive after its verified User lifecycle accepted a deletion."""

import hashlib

from folioview_shared.encrypted import legacy_archive, private_resources
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import signing_input_fingerprint
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json
from folioview_shared.encrypted.legacy_archive import (
    PROFILE,
    verify_legacy_archive_command,
    verify_legacy_archive_history,
)
from folioview_shared.identity import owner_key

from .store import StoreUnavailable, document_path, private_resource_writer_fence_path
from .user_vault_authority import scoped_user_vaults
from .vaults import _current, identifier


def _proof_path(owner, vault):
    return document_path("hub_operations", owner, "retired_archive", vault)


def _require_fence(fence, row):
    if not (
        type(fence) is dict
        and all(fence.get(k) == row[k] for k in ("ownerSubject", "vaultId", "rootKeyId"))
        and fence.get("state") == "transferred"
        and type(fence.get("writerEpoch")) is int
        and fence["writerEpoch"] == 2
    ):
        raise ContractError("authorization_unavailable")


def verified_retirement(unit, row, registry, lifecycle, now):
    owner, vault = row["ownerSubject"], row["vaultId"]
    proof = unit.get(_proof_path(owner, vault))
    if proof is None:
        return False
    fence = unit.get(private_resource_writer_fence_path(owner))
    _require_fence(fence, row)
    if proof.keys() != {"ownerSubject", "transition"} or proof["ownerSubject"] != owner:
        raise StoreUnavailable
    legacy_archive.verify_retired_archive_history(
        row,
        registry,
        lifecycle,
        proof["transition"],
        fingerprint=fence["transitionFingerprint"],
        now=now,
    )
    return True


def _verify_deletion(current, row, boundary, now):
    item = current.retirement
    if type(item) is not dict or set(item) != {"command", "receipt"}:
        raise ContractError("authorization_unavailable")
    command = verify_legacy_archive_command(item["command"], row)
    if (
        command["action"] != "archive_delete"
        or not boundary["nextVaultVersion"]
        <= command["expectedVaultVersion"]
        <= current.authority["vaultVersion"]
        or not boundary["nextHead"]["registrySequence"]
        <= command["registrySequence"]
        <= current.cursor.registry.registry_sequence
        or command["expectedLifecycleVersion"] < boundary["archive"]["version"] - 1
    ):
        raise ContractError("version_conflict")
    receipt = item["receipt"]
    accepted = receipt.get("acceptedAt") if type(receipt) is dict else None
    if (
        type(accepted) is not int
        or not command["issuedAt"] <= accepted < command["expiresAt"]
        or accepted > now
    ):
        raise ContractError("authorization_unavailable")
    if receipt != {
        "profile": PROFILE,
        "ownerSubject": row["ownerSubject"],
        "vaultId": row["vaultId"],
        "rootKeyId": row["rootKeyId"],
        "operationId": command["stableOperationId"],
        "action": "archive_delete",
        "lifecycleVersion": command["expectedLifecycleVersion"] + 1,
        "archiveRevision": command["expectedArchiveRevision"] + 1,
        "archiveDigest": hashlib.sha256(canonical_json(None)).hexdigest(),
        "commandFingerprint": signing_input_fingerprint(item["command"]),
        "acceptedAt": accepted,
    }:
        raise ContractError("recipient_binding_mismatch")


def cleanup_retired_archive(service, uid, vault, *, scopes=None, apply=True):
    identifier(vault)
    owner = owner_key(uid)
    store = service.store
    result = {"contractVersion": CONTRACT_VERSION, "vaultId": vault, "remaining": 0}
    fence_path = private_resource_writer_fence_path(owner)

    def inspect(unit):
        existing = unit.get(document_path("hub_vaults", owner))
        if existing is None:
            return None
        if (existing.get("ownerSubject"), existing.get("vaultId")) != (owner, vault):
            raise ContractError("version_conflict")
        fence = unit.get(fence_path)
        _require_fence(fence, existing)
        return fence

    fence = store.transact(inspect)
    if fence is None:
        return result
    scopes = scopes if scopes is not None else scoped_user_vaults(store)
    if not scopes.client or scopes.owner != owner:
        raise ContractError("authorization_unavailable")
    current = scopes.client.read(uid, vault, fence, retirement=True)

    def cleanup(unit):
        now = service.now()
        current.require_current(unit, now)
        row, registry = _current(unit, owner, now, vault)
        _require_fence(fence, row)
        transition = current.authority["signedTransition"]
        boundary = private_resources.verify_private_registry_transition_payload(
            transition, row["rootJwk"], row["rootKeyId"]
        )
        _verify_deletion(current, row, boundary, now)
        lifecycle = unit.get(document_path("hub_vault_lifecycle", owner, vault))
        if row["archive"] is not None:
            state = verify_legacy_archive_history(row, registry, lifecycle)
            if boundary["archive"] != {
                "state": "active",
                "digest": state["digest"],
                "version": state["version"] + 1,
            }:
                raise ContractError("version_conflict")
            retired = {**row, "archive": None}
            legacy_archive.verify_retired_archive_history(
                retired,
                registry,
                lifecycle,
                transition,
                fingerprint=fence["transitionFingerprint"],
                now=now,
            )
            if not apply:
                return {**result, "remaining": 1}
            unit.put(_proof_path(owner, vault), {"ownerSubject": owner, "transition": transition})
            unit.put(document_path("hub_vaults", owner), retired)
        return result

    return store.transact(cleanup)
