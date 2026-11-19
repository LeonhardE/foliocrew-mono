"""Shared verification for Root-approved Owner key renewal and archive rewrapping."""

from collections.abc import Mapping

from . import legacy_archive
from .budgets import check_read_response
from .constants import CONTRACT_VERSION
from .crypto import signing_input_fingerprint, verify_jws
from .errors import ContractError
from .jsonutil import canonical_json
from .legacy_archive import _digest
from .legacy_archive import _identifier as identifier
from .legacy_archive import _positive as positive
from .schema import validate_schema

PROFILE = "folioview.vault-key-renewal.v1"

MAX_CERTIFICATE_SECONDS = 31_536_000

_OWNER_ROLES = frozenset({"device_sig", "device_enc", "recovery_enc"})

_TARGET_FIELDS = frozenset(
    {"role", "principalId", "priorKeyId", "newKeyId", "priorKeyEpoch", "newKeyEpoch"}
)

_FIELDS = frozenset(
    {
        "profile",
        "contractVersion",
        "action",
        "ownerSubject",
        "vaultId",
        "rootKeyId",
        "stableOperationId",
        "expectedVaultVersion",
        "registrySequence",
        "checkpointDigest",
        "keyEpoch",
        "expectedLifecycleVersion",
        "expectedArchiveRevision",
        "expectedArchiveDigest",
        "newCheckpointDigest",
        "newArchiveDigest",
        "archiveCommandFingerprint",
        "renewals",
        "issuedAt",
        "expiresAt",
    }
)

_COMMON = (
    "ownerSubject",
    "vaultId",
    "rootKeyId",
    "stableOperationId",
    "expectedVaultVersion",
    "registrySequence",
    "checkpointDigest",
    "keyEpoch",
    "expectedLifecycleVersion",
    "expectedArchiveRevision",
    "expectedArchiveDigest",
    "newArchiveDigest",
)


def _plain(value):
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


def verify_owner_renewal_command(command, row):
    """Verify an exact Owner renewal command under the vault Root."""
    if len(canonical_json(command)) > legacy_archive.MAX_COMMAND_BYTES:
        raise ContractError("payload_too_large")
    p = verify_jws(command, row["rootJwk"], typ="fv-control+jws", expected_kid=row["rootKeyId"])
    if set(p) != _FIELDS:
        raise ContractError("malformed_request")
    if p["profile"] != PROFILE:
        raise ContractError("unsupported_profile")
    if p["contractVersion"] != CONTRACT_VERSION:
        raise ContractError("unsupported_contract")
    if p["action"] != "key_renewal":
        raise ContractError("malformed_request")
    if any(p[f] != row[f] for f in ("ownerSubject", "vaultId", "rootKeyId")):
        raise ContractError("recipient_binding_mismatch")
    validate_schema("OperationIdentifier", p["stableOperationId"])
    for f in ("expectedVaultVersion", "registrySequence", "keyEpoch", "expiresAt"):
        positive(p[f])
    for f in ("expectedLifecycleVersion", "expectedArchiveRevision", "issuedAt"):
        positive(p[f], zero=True)
    for f in (
        "checkpointDigest",
        "expectedArchiveDigest",
        "newCheckpointDigest",
        "newArchiveDigest",
        "archiveCommandFingerprint",
    ):
        _digest(p[f])
    if not p["issuedAt"] < p["expiresAt"] <= p["issuedAt"] + 300:
        raise ContractError("malformed_request")
    targets = p["renewals"]
    if type(targets) is not list or not 1 <= len(targets) <= 3:
        raise ContractError("malformed_request")
    roles, old, new, order = set(), set(), set(), []
    for t in targets:
        if (
            type(t) is not dict
            or set(t) != _TARGET_FIELDS
            or type(t["role"]) is not str
            or t["role"] not in _OWNER_ROLES
        ):
            raise ContractError("malformed_request")
        identifier(t["principalId"])
        for f in ("priorKeyId", "newKeyId"):
            validate_schema("KeyId", t[f])
        for f in ("priorKeyEpoch", "newKeyEpoch"):
            positive(t[f])
        if t["newKeyEpoch"] != t["priorKeyEpoch"] + 1:
            raise ContractError("stale_key_epoch")
        if t["role"] in roles or t["priorKeyId"] in old or t["newKeyId"] in new:
            raise ContractError("malformed_request")
        roles.add(t["role"])
        old.add(t["priorKeyId"])
        new.add(t["newKeyId"])
        order.append((t["role"], t["principalId"], t["priorKeyId"]))
    if (
        old & new
        or order != sorted(order)
        or roles not in ({"recovery_enc"}, {"device_sig", "device_enc"}, set(_OWNER_ROLES))
    ):
        raise ContractError("key_authorization_required")
    devices = [t["principalId"] for t in targets if t["role"].startswith("device_")]
    if len(set(devices)) > 1:
        raise ContractError("recipient_binding_mismatch")
    return p


def verify_owner_renewal_archive(p, command, row):
    """Match the paired archive rewrap command to the same signed operation."""
    ap = legacy_archive.verify_legacy_archive_command(command, row)
    if (
        ap["action"] != "archive_replace"
        or ap["mode"] != "rewrap"
        or ap["authorizationId"] is not None
    ):
        raise ContractError("recipient_binding_mismatch")
    if any(p[f] != ap[f] for f in _COMMON) or p[
        "archiveCommandFingerprint"
    ] != signing_input_fingerprint(command):
        raise ContractError("recipient_binding_mismatch")
    return ap


def require_fresh_renewal_keys(payload, registries):
    """Ensure a successor key has not appeared in an earlier generation."""
    known = {kid for registry in registries for kid in registry.certificates}
    if any(target["newKeyId"] in known for target in payload["renewals"]):
        raise ContractError("registry_conflict")


def verify_owner_renewal_delta(p, previous, next_registry, at):
    """Check the exact certificate change and the usable remaining Owner keys."""
    if (
        previous.registry_sequence != p["registrySequence"]
        or previous.checkpoint_digest != p["checkpointDigest"]
        or previous.key_epoch != p["keyEpoch"]
        or next_registry.registry_sequence != previous.registry_sequence + 1
        or next_registry.key_epoch != previous.key_epoch
        or next_registry.root_epoch != previous.root_epoch
        or next_registry.checkpoint_digest != p["newCheckpointDigest"]
    ):
        raise ContractError("registry_conflict")
    old_ids = {t["priorKeyId"] for t in p["renewals"]}
    new_ids = {t["newKeyId"] for t in p["renewals"]}
    if set(next_registry.certificates) != set(previous.certificates) | new_ids or new_ids & set(
        previous.certificates
    ):
        raise ContractError("registry_conflict")
    if (
        set(next_registry.revoked_key_ids) != set(previous.revoked_key_ids) | old_ids
        or set(next_registry.active_key_ids) != (set(previous.active_key_ids) - old_ids) | new_ids
    ):
        raise ContractError("key_authorization_required")
    for kid, old in previous.certificates.items():
        if canonical_json(_plain(old)) != canonical_json(_plain(next_registry.certificates[kid])):
            raise ContractError("registry_conflict")
    for t in p["renewals"]:
        old = previous.certificates.get(t["priorKeyId"])
        new = next_registry.certificates.get(t["newKeyId"])
        if (
            old is None
            or new is None
            or t["priorKeyId"] not in previous.active_key_ids
            or t["priorKeyId"] in previous.revoked_key_ids
        ):
            raise ContractError("key_authorization_required")
        identity = (t["principalId"], t["role"], None)
        if (
            old["keyEpoch"] != previous.local_key_epochs.get(identity)
            or old["keyEpoch"] != t["priorKeyEpoch"]
            or new["keyEpoch"] != t["newKeyEpoch"]
        ):
            raise ContractError("stale_key_epoch")
        if (
            any(old[f] != new[f] for f in ("role", "principalId", "connectionId", "capabilities"))
            or old["role"] != t["role"]
            or old["principalId"] != t["principalId"]
            or old["connectionId"] is not None
        ):
            raise ContractError("recipient_binding_mismatch")
        if not (
            p["issuedAt"] - 300 <= new["notBefore"] <= p["issuedAt"] <= at < new["expiresAt"]
            and new["expiresAt"] > old["expiresAt"]
            and new["expiresAt"] - new["notBefore"] <= MAX_CERTIFICATE_SECONDS
        ):
            raise ContractError("key_authorization_required")
    require_owner_recipients(next_registry, at)


def owner_renewal_response(receipt):
    """Return the bounded public receipt envelope."""
    result = {"contractVersion": CONTRACT_VERSION, "profile": PROFILE, "receipt": receipt}
    check_read_response(result)
    return result


def owner_renewal_receipt(row, p, registry, state, command, at):
    """Derive a receipt from the accepted command and the two advanced records."""
    return {
        "profile": PROFILE,
        "ownerSubject": row["ownerSubject"],
        "vaultId": row["vaultId"],
        "rootKeyId": row["rootKeyId"],
        "operationId": p["stableOperationId"],
        "vaultVersion": p["expectedVaultVersion"] + 1,
        "registrySequence": registry.registry_sequence,
        "checkpointDigest": registry.checkpoint_digest,
        "keyEpoch": registry.key_epoch,
        "lifecycleVersion": state["version"],
        "archiveRevision": state["revision"],
        "archiveDigest": state["digest"],
        "renewals": p["renewals"],
        "commandFingerprint": signing_input_fingerprint(command),
        "archiveCommandFingerprint": p["archiveCommandFingerprint"],
        "acceptedAt": at,
    }


def require_owner_recipients(registry, now):
    """Select existing valid writer and reader keys after a registry change."""
    writers, recipients, roles = [], [], set()
    for kid in sorted(registry.active_key_ids):
        try:
            cert = registry.cert(kid, connection_id=None, now=now)
        except ContractError:
            continue
        if cert["role"] == "device_sig" and "object_write" in cert["capabilities"]:
            writers.append(kid)
        if cert["role"] in {"device_enc", "recovery_enc"}:
            recipients.append(kid)
            roles.add(cert["role"])
    if (
        not 1 <= len(writers) <= 8
        or not 2 <= len(recipients) <= 8
        or roles != {"device_enc", "recovery_enc"}
    ):
        raise ContractError("key_authorization_required")
    return writers, recipients


def owner_renewal_state(row, registry, state, now):
    """Build the exact public view of the current archive and Owner keys."""
    vault = row["vaultId"]
    certificates = []
    for kid in sorted(registry.certificates):
        c = registry.certificates[kid]
        if c["role"] not in _OWNER_ROLES:
            continue
        status = "active"
        if kid in registry.revoked_key_ids:
            status = "revoked"
        elif c["keyEpoch"] != registry.local_key_epochs.get((c["principalId"], c["role"], None)):
            status = "superseded"
        elif now < c["notBefore"]:
            status = "not_yet_valid"
        elif now >= c["expiresAt"]:
            status = "expired"
        certificates.append(
            {
                "keyId": kid,
                "role": c["role"],
                "principalId": c["principalId"],
                "keyEpoch": c["keyEpoch"],
                "notBefore": c["notBefore"],
                "expiresAt": c["expiresAt"],
                "status": status,
            }
        )
    result = {
        "contractVersion": CONTRACT_VERSION,
        "profile": PROFILE,
        "vaultId": vault,
        "rootKeyId": row["rootKeyId"],
        "rootAnchorExpiresAt": None,
        "vaultVersion": row["version"],
        "registrySequence": registry.registry_sequence,
        "checkpointDigest": registry.checkpoint_digest,
        "keyEpoch": registry.key_epoch,
        "lifecycleVersion": state["version"],
        "archiveRevision": state["revision"],
        "archiveDigest": state["digest"],
        "pendingRecoveryAuthorization": state["pending"] is not None,
        "certificates": certificates,
    }
    check_read_response(result)
    return result
