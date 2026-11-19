"""Prepared copies of original operation records and invalidation acknowledgements."""

from datetime import datetime

from folioview_shared.encrypted.constants import CONTRACT_VERSION, MAX_SAFE_INTEGER
from folioview_shared.encrypted.crypto import jwk_thumbprint, verify_jws
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json, strict_json_loads
from folioview_shared.encrypted.legacy_archive import verify_legacy_archive_command
from folioview_shared.encrypted.schema import validate_schema

from .legacy_baselines import _DIGEST, MAX_BASELINE_BYTES, _scope, _sha

PROFILE = "folioview.private-original-operation-baseline.v1"
KEY_RENEWAL = "folioview.vault-key-renewal.v1"
MAX_BATCH = 64


def _decode(value):
    if type(value) is not dict or len(value) != 1:
        raise ValueError
    kind, item = next(iter(value.items()))
    if kind == "stringValue" and type(item) is str:
        return item
    if kind == "integerValue" and type(item) is str and str(int(item)) == item:
        return int(item)
    if kind == "booleanValue" and type(item) is bool:
        return item
    if kind == "nullValue" and item is None:
        return None
    if kind == "arrayValue" and type(item) is dict and item.keys() <= {"values"}:
        return [_decode(entry) for entry in item.get("values", [])]
    if kind == "mapValue" and type(item) is dict and item.keys() <= {"fields"}:
        return _fields(item.get("fields", {}))
    raise ValueError


def _fields(fields):
    if type(fields) is not dict:
        raise ValueError
    return {key: _decode(value) for key, value in fields.items()}


def _fence(vault, key, record):
    if record.keys() != {"request", "fingerprint", "ack"}:
        raise ValueError
    owner = vault["ownerSubject"]
    request, ack = record["request"], record["ack"]
    fields = {
        "contractVersion",
        "ownerSubject",
        "mutationId",
        "ref",
        "expectedSourceEpoch",
        "newSourceEpoch",
        "reason",
    }
    if (
        request.keys() != fields
        or request["ownerSubject"] != owner
        or request["contractVersion"] != CONTRACT_VERSION
        or request["reason"] not in {"account_scope_changed", "disconnected", "deleted"}
    ):
        raise ValueError
    mutation, reference = request["mutationId"], request["ref"]
    validate_schema("OperationIdentifier", mutation)
    validate_schema("ResourceRef", reference)
    if reference["sourceService"] != "portfolio" or reference["kind"] != "holdings":
        raise ValueError
    if not any(anchor["resourceRef"] == reference for anchor in vault["sources"]):
        raise ValueError
    prior, following = request["expectedSourceEpoch"], request["newSourceEpoch"]
    if (
        type(prior) is not int
        or type(following) is not int
        or not 1 <= prior < following <= MAX_SAFE_INTEGER
        or following != prior + 1
    ):
        raise ValueError
    at = ack["acknowledgedAt"]
    if type(at) is not str or not at.endswith("Z"):
        raise ValueError
    datetime.fromisoformat(at.replace("Z", "+00:00"))
    if (
        ack
        != {
            "contractVersion": CONTRACT_VERSION,
            "mutationId": mutation,
            "ref": reference,
            "acknowledgedSourceEpoch": following,
            "acknowledgedAt": at,
        }
        or type(ack["acknowledgedSourceEpoch"]) is not int
        or record["fingerprint"] != _sha(canonical_json(request))
        or key != _sha(canonical_json([owner, "portfolio", mutation]))
    ):
        raise ValueError


def _vault_operation(vault, key, record):
    owner, root = vault["ownerSubject"], vault["rootKeyId"]
    if record["ownerSubject"] != owner:
        raise ValueError
    if record.get("kind") in {"bootstrap", "registry", "source"}:
        if record.keys() != {"ownerSubject", "kind", "fingerprint"} or not _DIGEST.fullmatch(
            record["fingerprint"]
        ):
            raise ValueError
        # The original operation ID is represented by its saved physical key.
        return
    if record.get("profile") != KEY_RENEWAL or record.keys() != {
        "profile",
        "ownerSubject",
        "vaultId",
        "rootKeyId",
        "command",
        "archiveCommand",
        "receipt",
    }:
        raise ValueError
    command = verify_jws(
        record["command"], vault["rootJwk"], typ="fv-control+jws", expected_kid=root
    )
    archive = verify_legacy_archive_command(record["archiveCommand"], vault)
    operation = command["stableOperationId"]
    validate_schema("OperationIdentifier", operation)
    if (
        key != _sha(canonical_json([owner, "key-renewal", operation]))
        or archive["stableOperationId"] != operation
        or command["profile"] != KEY_RENEWAL
        or any(
            record[name] != command[name] or command[name] != vault[name]
            for name in ("ownerSubject", "vaultId", "rootKeyId")
        )
        or record["receipt"]["operationId"] != operation
    ):
        raise ValueError


def original_operation_baseline(owner, vault, records):
    """Keep the exact type-tagged source fields under their original physical keys."""
    try:
        _scope(owner, vault["vaultId"])
        if owner != vault["ownerSubject"] or jwk_thumbprint(vault["rootJwk"]) != vault["rootKeyId"]:
            raise ValueError
        if type(records) is not dict or not records or len(records) > MAX_BATCH:
            raise ValueError
        handlers = {"hub_operations": _vault_operation, "hub_fence_mutations": _fence}
        for path, fields in records.items():
            collection, _, key = path.partition("/")
            if collection not in handlers or not _DIGEST.fullmatch(key):
                raise ValueError
            handlers[collection](vault, key, _fields(fields))
        encoded = canonical_json(
            {
                "profile": PROFILE,
                "ownerSubject": owner,
                "vaultId": vault["vaultId"],
                "rootKeyId": vault["rootKeyId"],
                "originalOperations": records,
            }
        )
    except (ContractError, AttributeError, TypeError, KeyError, ValueError, RecursionError):
        raise ContractError("authorization_unavailable") from None
    if len(encoded) > MAX_BASELINE_BYTES:
        raise ContractError("payload_too_large")
    return encoded


def original_fence_receipts(baseline, data):
    """Restore verified ACKs to their original operation keys for authoritative replay."""
    try:
        value = strict_json_loads(data, max_bytes=MAX_BASELINE_BYTES)
        scope = {key: baseline[key] for key in ("ownerSubject", "vaultId", "rootKeyId")}
        if (
            value.keys() != {*scope, "profile", "originalOperations"}
            or value["profile"] != PROFILE
            or any(value[key] != expected for key, expected in scope.items())
        ):
            raise ValueError
        records = value["originalOperations"]
        if type(records) is not dict or not 1 <= len(records) <= MAX_BATCH:
            raise ValueError
        result = {}
        for path, fields in records.items():
            collection, _, key = path.partition("/")
            if collection != "hub_fence_mutations":
                continue
            record = _fields(fields)
            _fence(baseline, key, record)
            result[key] = {
                "ownerSubject": scope["ownerSubject"],
                "vaultId": scope["vaultId"],
                **record,
            }
        return result
    except (AttributeError, ContractError, TypeError, KeyError, ValueError, RecursionError):
        raise ContractError("authorization_unavailable") from None


def original_key_renewal(vault, data, operation):
    """Read only the requested original renewal from the verified same-Root baseline."""
    try:
        validate_schema("OperationIdentifier", operation)
        owner = vault["ownerSubject"]
        value = strict_json_loads(data, max_bytes=MAX_BASELINE_BYTES)
        if (
            value.keys()
            != {"profile", "ownerSubject", "vaultId", "rootKeyId", "originalOperations"}
            or value["profile"] != PROFILE
            or any(value[key] != vault[key] for key in ("ownerSubject", "vaultId", "rootKeyId"))
        ):
            raise ValueError
        records = value["originalOperations"]
        if type(records) is not dict or not 1 <= len(records) <= MAX_BATCH:
            raise ValueError
        key = _sha(canonical_json([owner, "key-renewal", operation]))
        fields = records.get("hub_operations/" + key)
        if fields is None:
            return None
        record = _fields(fields)
        _vault_operation(vault, key, record)
        return record
    except (AttributeError, ContractError, TypeError, KeyError, ValueError, RecursionError):
        raise ContractError("authorization_unavailable") from None
