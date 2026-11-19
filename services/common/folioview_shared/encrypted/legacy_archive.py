"""Original public Root proofs for Passkey archives and their legacy lifecycle receipts."""

import hashlib
import re

from .authority import VerifiedRegistry
from .constants import CONTRACT_VERSION, MAX_CONTROL_BYTES, MAX_SAFE_INTEGER
from .crypto import jwk_thumbprint, signing_input_fingerprint, verify_jws
from .errors import ContractError
from .jsonutil import b64url_decode, canonical_json, strict_json_loads
from .schema import validate_schema

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_ARCHIVE_FIELDS = frozenset(
    {
        "profile",
        "ownerSubject",
        "vaultId",
        "rootKeyId",
        "credentialId",
        "prfSalt",
        "iv",
        "ciphertext",
    }
)


def _identifier(value):
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ContractError("malformed_request")


def _positive(value, *, zero=False):
    if type(value) is not int or not (0 if zero else 1) <= value <= MAX_SAFE_INTEGER:
        raise ContractError("malformed_request")


def validate_passkey_archive(value, *, owner, vault, root):
    if type(value) is not dict or set(value) != _ARCHIVE_FIELDS:
        raise ContractError("malformed_request")
    if (
        value["profile"] != "folioview.passkey-vault.v1"
        or value["ownerSubject"] != owner
        or value["vaultId"] != vault
        or value["rootKeyId"] != root
    ):
        raise ContractError("recipient_binding_mismatch")
    for field, minimum, maximum in (
        ("credentialId", 1, 1536),
        ("prfSalt", 32, 32),
        ("iv", 12, 12),
        ("ciphertext", 16, 24576),
    ):
        text = value[field]
        if (
            type(text) is not str
            or (field == "credentialId" and len(text) > 2048)
            or (field == "ciphertext" and len(text) > 32768)
        ):
            raise ContractError("malformed_request")
        raw = b64url_decode(text, max_bytes=maximum)
        if not minimum <= len(raw) <= maximum:
            raise ContractError("malformed_request")
    return value


PROFILE = "folioview.vault-lifecycle.v1"
MAX_LIFECYCLE_OPERATIONS = 32
MAX_AUTHORIZATION_SECONDS = 300
MAX_COMMAND_BYTES = 8192
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_BASE_FIELDS = frozenset(
    {
        "profile",
        "contractVersion",
        "action",
        "ownerSubject",
        "vaultId",
        "rootKeyId",
        "stableOperationId",
        "expectedVaultVersion",
        "expectedLifecycleVersion",
        "expectedArchiveRevision",
        "expectedArchiveDigest",
        "registrySequence",
        "checkpointDigest",
        "keyEpoch",
        "issuedAt",
        "expiresAt",
    }
)
_ACTION_FIELDS = {
    "archive_replace": frozenset({"mode", "newArchiveDigest", "authorizationId"}),
    "archive_delete": frozenset(),
    "archive_delete_withdraw": frozenset(
        {"deletionOperationId", "deletionCommandFingerprint", "deletionLifecycleVersion"}
    ),
    "recovery_authorize": frozenset({"authorizationId", "newArchiveDigest"}),
    "recovery_revoke": frozenset({"authorizationId"}),
}
_RECEIPT_FIELDS = frozenset(
    {
        "profile",
        "ownerSubject",
        "vaultId",
        "rootKeyId",
        "operationId",
        "action",
        "lifecycleVersion",
        "archiveRevision",
        "archiveDigest",
        "commandFingerprint",
        "acceptedAt",
    }
)
_ROW_FIELDS = frozenset({"ownerSubject", "vaultId", "rootKeyId", "initialArchiveDigest", "history"})
_FENCE_FIELDS = (
    "expectedVaultVersion",
    "registrySequence",
    "checkpointDigest",
    "keyEpoch",
)


def _digest(value):
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ContractError("malformed_request")


def verify_legacy_archive_command(command, vault):
    if len(canonical_json(command)) > MAX_COMMAND_BYTES:
        raise ContractError("payload_too_large")
    value = verify_jws(
        command, vault["rootJwk"], typ="fv-control+jws", expected_kid=vault["rootKeyId"]
    )
    action = value.get("action")
    if (
        type(action) is not str
        or action not in _ACTION_FIELDS
        or set(value) != _BASE_FIELDS | _ACTION_FIELDS[action]
    ):
        raise ContractError("malformed_request")
    if value["profile"] != PROFILE:
        raise ContractError("unsupported_profile")
    if value["contractVersion"] != CONTRACT_VERSION:
        raise ContractError("unsupported_contract")
    if any(value[field] != vault[field] for field in ("ownerSubject", "vaultId", "rootKeyId")):
        raise ContractError("recipient_binding_mismatch")
    validate_schema("OperationIdentifier", value["stableOperationId"])
    for field in ("expectedVaultVersion", "registrySequence", "keyEpoch", "expiresAt"):
        _positive(value[field])
    for field in ("expectedLifecycleVersion", "expectedArchiveRevision", "issuedAt"):
        _positive(value[field], zero=True)
    _digest(value["expectedArchiveDigest"])
    _digest(value["checkpointDigest"])
    if not value["issuedAt"] < value["expiresAt"] <= value["issuedAt"] + MAX_AUTHORIZATION_SECONDS:
        raise ContractError("malformed_request")
    if action in {"archive_replace", "recovery_authorize"}:
        _digest(value["newArchiveDigest"])
    if action == "archive_replace":
        if value["mode"] not in ("rewrap", "passkey_change", "recovery"):
            raise ContractError("malformed_request")
        if value["mode"] != "recovery":
            if value["authorizationId"] is not None:
                raise ContractError("malformed_request")
        else:
            _identifier(value["authorizationId"])
    elif action in {"recovery_authorize", "recovery_revoke"}:
        _identifier(value["authorizationId"])
    elif action == "archive_delete_withdraw":
        validate_schema("OperationIdentifier", value["deletionOperationId"])
        _digest(value["deletionCommandFingerprint"])
        _positive(value["deletionLifecycleVersion"], zero=True)
        if value["deletionOperationId"] == value["stableOperationId"]:
            raise ContractError("idempotency_conflict")
    return value


def advance_legacy_archive(state, payload, command, accepted_at):
    """Apply signed public semantics both on new writes and on persisted history."""
    if not payload["issuedAt"] <= accepted_at < payload["expiresAt"]:
        raise ContractError("key_authorization_required")
    if accepted_at < state["lastAcceptedAt"]:
        raise ContractError("version_conflict")
    if (
        payload["expectedLifecycleVersion"] != state["version"]
        or payload["expectedArchiveRevision"] != state["revision"]
        or payload["expectedArchiveDigest"] != state["digest"]
    ):
        raise ContractError("version_conflict")
    action = payload["action"]
    pending = state["pending"]
    next_state = {
        **state,
        "version": state["version"] + 1,
        "lastAcceptedAt": accepted_at,
        "lastVaultVersion": payload["expectedVaultVersion"],
        "lastRegistrySequence": payload["registrySequence"],
    }
    if action == "recovery_authorize":
        # A newly granted approval must retain one slot to consume or revoke it.
        # The same rule is checked while authenticating stored history.
        if state["version"] >= MAX_LIFECYCLE_OPERATIONS - 1:
            raise ContractError("version_conflict")
        if payload["newArchiveDigest"] == state["digest"]:
            raise ContractError("recipient_binding_mismatch")
        if payload["authorizationId"] in state["authorizationIds"]:
            raise ContractError("version_conflict")
        if pending is not None and accepted_at < pending["payload"]["expiresAt"]:
            raise ContractError("version_conflict")
        next_state["pending"] = {"payload": payload, "command": command}
        next_state["authorizationIds"] = state["authorizationIds"] | {payload["authorizationId"]}
    elif action == "recovery_revoke":
        if pending is None or pending["payload"]["authorizationId"] != payload["authorizationId"]:
            raise ContractError("key_authorization_required")
        next_state["pending"] = None
    elif action == "archive_delete":
        # Leave room for a fresh approval and restore from independent material.
        if (
            state["deleted"]
            or payload["stableOperationId"] in state["withdrawn"]
            or state["version"] > MAX_LIFECYCLE_OPERATIONS - 3
        ):
            raise ContractError("version_conflict")
        next_state.update(
            revision=state["revision"] + 1,
            digest=_digest_value(None),
            pending=None,
            deleted=True,
        )
    elif action == "archive_delete_withdraw":
        target = payload["deletionOperationId"]
        if (
            state["deleted"]
            or target in state["operations"]
            or target in state["withdrawn"]
            or payload["deletionLifecycleVersion"] > state["version"]
        ):
            raise ContractError("version_conflict")
        # This signed lifecycle advance permanently invalidates the original CAS.
        # It preserves the archive/revision, pending recovery and all other keys.
        next_state["withdrawn"] = {**state["withdrawn"], target: payload}
    else:
        if payload["newArchiveDigest"] == state["digest"]:
            raise ContractError("recipient_binding_mismatch")
        if payload["mode"] == "recovery":
            if pending is None:
                raise ContractError("key_authorization_required")
            grant = pending["payload"]
            if (
                grant["authorizationId"] != payload["authorizationId"]
                or grant["newArchiveDigest"] != payload["newArchiveDigest"]
                or grant["expectedArchiveRevision"] != payload["expectedArchiveRevision"]
                or grant["expectedArchiveDigest"] != payload["expectedArchiveDigest"]
                or any(grant[field] != payload[field] for field in _FENCE_FIELDS)
                or not grant["issuedAt"] <= payload["issuedAt"] <= accepted_at < grant["expiresAt"]
                or payload["expiresAt"] > grant["expiresAt"]
            ):
                raise ContractError("key_authorization_required")
        elif state["deleted"]:
            raise ContractError("key_authorization_required")
        next_state.update(
            revision=state["revision"] + 1,
            digest=payload["newArchiveDigest"],
            pending=None,
            deleted=False,
        )
    return next_state


def legacy_archive_receipt(vault, payload, state, command, accepted_at):
    return {
        "profile": PROFILE,
        "ownerSubject": vault["ownerSubject"],
        "vaultId": vault["vaultId"],
        "rootKeyId": vault["rootKeyId"],
        "operationId": payload["stableOperationId"],
        "action": payload["action"],
        "lifecycleVersion": state["version"],
        "archiveRevision": state["revision"],
        "archiveDigest": state["digest"],
        "commandFingerprint": signing_input_fingerprint(command),
        "acceptedAt": accepted_at,
    }


def verify_legacy_archive_history(vault, registry, row):
    """Verify legacy archive receipts against the original, independently verified registry head."""
    try:
        return _verify_history(vault, registry, row)
    except (ContractError, KeyError, TypeError, ValueError, AttributeError, RecursionError):
        raise ContractError("authorization_unavailable") from None


def _verify_history(vault, registry, row):
    if not isinstance(registry, VerifiedRegistry) or (
        vault["ownerSubject"] != registry.owner_subject
        or vault["vaultId"] != registry.vault_id
        or vault["rootKeyId"] != registry.root_key_id
        or registry.root_epoch != 1
        or jwk_thumbprint(vault["rootJwk"]) != registry.root_key_id
    ):
        raise ContractError("authorization_unavailable")
    _positive(vault["version"])
    scope = {
        "owner": registry.owner_subject,
        "vault": registry.vault_id,
        "root": registry.root_key_id,
    }
    if vault["archive"] is not None:
        validate_passkey_archive(vault["archive"], **scope)
    elif row is None:
        raise ContractError("authorization_unavailable")
    current_digest = _digest_value(vault["archive"])
    initial = (
        current_digest
        if row is None
        else row.get("initialArchiveDigest")
        if type(row) is dict
        else None
    )
    state = {
        "version": 0,
        "revision": 0,
        "digest": initial,
        "pending": None,
        "deleted": False,
        "authorizationIds": set(),
        "operations": {},
        "withdrawn": {},
        "lastAcceptedAt": 0,
        "lastVaultVersion": 0,
        "lastRegistrySequence": 0,
    }
    if row is None:
        return state
    if (
        type(row) is not dict
        or set(row) != _ROW_FIELDS
        or any(row[field] != vault[field] for field in ("ownerSubject", "vaultId", "rootKeyId"))
        or type(row["history"]) is not list
        or not 1 <= len(row["history"]) <= MAX_LIFECYCLE_OPERATIONS
    ):
        raise ContractError("authorization_unavailable")
    _digest(initial)
    checkpoints = _verified_checkpoints(vault["registryHistory"], registry)
    for item in row["history"]:
        if type(item) is not dict or set(item) != {"command", "receipt"}:
            raise ContractError("authorization_unavailable")
        payload = verify_legacy_archive_command(item["command"], vault)
        receipt = item["receipt"]
        if type(receipt) is not dict or set(receipt) != _RECEIPT_FIELDS:
            raise ContractError("authorization_unavailable")
        _positive(receipt["acceptedAt"], zero=True)
        _positive(receipt["lifecycleVersion"])
        _positive(receipt["archiveRevision"], zero=True)
        if (
            not state["lastVaultVersion"] <= payload["expectedVaultVersion"] <= vault["version"]
            or not state["lastRegistrySequence"]
            <= payload["registrySequence"]
            <= registry.registry_sequence
        ):
            raise ContractError("authorization_unavailable")
        checkpoint = checkpoints[payload["registrySequence"]]
        if (
            payload["checkpointDigest"] != checkpoint["digest"]
            or payload["keyEpoch"] != checkpoint["keyEpoch"]
            or payload["stableOperationId"] in state["operations"]
        ):
            raise ContractError("authorization_unavailable")
        advanced = advance_legacy_archive(state, payload, item["command"], receipt["acceptedAt"])
        if receipt != legacy_archive_receipt(
            vault, payload, advanced, item["command"], receipt["acceptedAt"]
        ):
            raise ContractError("authorization_unavailable")
        advanced["operations"] = {**state["operations"], payload["stableOperationId"]: item}
        state = advanced
    if state["digest"] != current_digest or state["deleted"] != (vault["archive"] is None):
        raise ContractError("authorization_unavailable")
    return state


def _digest_value(value):
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _verified_checkpoints(history, registry):
    # The verified current digest anchors all preceding canonical checkpoints.
    # It never elevates these archived certificate generations into live authority.
    if type(history) is not list or not 1 <= len(history) == registry.registry_sequence <= 32:
        raise ContractError("authorization_unavailable")
    expected_digest = registry.checkpoint_digest
    checkpoints = {}
    for sequence in range(len(history), 0, -1):
        raw = b64url_decode(
            history[sequence - 1]["checkpoint"]["payload"], max_bytes=MAX_CONTROL_BYTES
        )
        payload = strict_json_loads(raw, max_bytes=MAX_CONTROL_BYTES)
        validate_schema("RegistryCheckpointPayload", payload)
        if (
            hashlib.sha256(raw).hexdigest() != expected_digest
            or canonical_json(payload) != raw
            or payload["registrySequence"] != sequence
            or payload["rootKeyId"] != registry.root_key_id
            or payload["vaultId"] != registry.vault_id
            or payload["ownerSubject"] != registry.owner_subject
            or payload["rootEpoch"] != registry.root_epoch
        ):
            raise ContractError("authorization_unavailable")
        checkpoints[sequence] = {"digest": expected_digest, "keyEpoch": payload["keyEpoch"]}
        expected_digest = payload["previousDigest"]
    if expected_digest is not None:
        raise ContractError("authorization_unavailable")
    return checkpoints
