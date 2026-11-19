"""Contracts for the User private resource authority and its consumers.

Arguments described as authenticated or verified are supplied by the caller.
These functions perform no network, persistence, or permission issuance.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files

from jsonschema import Draft202012Validator

from .authority import RegistryCertificateMemo, VerifiedRegistry, verify_registry
from .constants import CONTRACT_VERSION, MAX_CONTEXT_BYTES, MAX_REGISTRY_BYTES, MAX_RESOURCES
from .crypto import verify_jws
from .errors import ContractError
from .jsonutil import canonical_json
from .schema import load_schema

REPORT_PROFILE = "folioview.report-source-authorization.v1"
RECOVERY_PROFILE = "folioview.owner-recovery-evidence.v1"
REPORT_PERMIT_SECONDS = 30
RECOVERY_EVIDENCE_SECONDS = 60
MAX_REGISTRY_PAGE_BYTES = 2 * MAX_REGISTRY_BYTES
_OWNER_ROLES = frozenset({"root_sig", "device_sig", "device_enc", "recovery_enc"})
_SCOPE = ("ownerSubject", "vaultId")
_ROOT_SCOPE = (*_SCOPE, "rootKeyId")


@lru_cache(maxsize=1)
def _document():
    doc = json.loads(files(__package__).joinpath("private_resources.json").read_text())
    legacy = load_schema("Identifier")["$defs"]
    if doc["$defs"].keys() & legacy.keys():
        raise RuntimeError("Private resource schema collision")
    return {**doc, "$defs": {**legacy, **doc["$defs"]}}


@lru_cache(maxsize=32)
def _validator(name: str):
    doc = _document()
    if name not in doc["$defs"]:
        raise ContractError("malformed_request")
    return Draft202012Validator({**doc, "$ref": f"#/$defs/{name}"})


def _validate(name: str, value, *, limit=MAX_CONTEXT_BYTES):
    if len(canonical_json(value)) > limit:
        raise ContractError("payload_too_large")
    if not _validator(name).is_valid(value):
        raise ContractError("malformed_request")
    return copy.deepcopy(value)


def _digest(value) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _scope_match(a: dict, b: dict, fields=_SCOPE):
    if any(a[field] != b[field] for field in fields):
        raise ContractError("recipient_binding_mismatch")


def _resource_key(binding: dict) -> tuple[str, str, str]:
    ref = binding["ref"]
    return ref["kind"], ref["sourceService"], ref["resourceId"]


def _require_unique_bindings(bindings):
    keys = [_resource_key(binding) for binding in bindings]
    if len(set(keys)) != len(keys):
        raise ContractError("malformed_request")


def report_source_request(request: dict) -> dict:
    """Freeze an exact attempt and deterministic transport digest input."""
    req = _validate("ReportSourceRequest", request)
    if req["attemptId"] == req["operationId"]:
        raise ContractError("malformed_request")
    _require_unique_bindings(req["resources"])
    return req


def decide_report_sources(request: dict, *, snapshot: dict, now: int) -> dict:
    """Project one authenticated, atomic User transaction read into a decision.

    The snapshot covers every requested logical resource and its current
    incarnation/epoch. A known absence is an explicit missing state. A failed
    or incomplete read raises unavailable and cannot yield a permission.
    """
    req = report_source_request(request)
    _validate("PrivateResourceTime", now)
    if snapshot is None:
        raise ContractError("source_unavailable")
    state = _validate("ReportSourceSnapshot", snapshot)
    _scope_match(req, state)
    _require_unique_bindings(item["binding"] for item in state["resources"])
    current = {_resource_key(item["binding"]): item for item in state["resources"]}
    if current.keys() != {_resource_key(binding) for binding in req["resources"]}:
        raise ContractError("source_unavailable")
    allowed = True
    for requested in req["resources"]:
        resource = current[_resource_key(requested)]
        if (
            resource["state"] != "eligible"
            or resource["binding"]["ref"] != requested["ref"]
            or resource["binding"]["sourceEpoch"] != requested["sourceEpoch"]
            or resource["currentRevision"] < requested["sourceRevision"]
        ):
            allowed = False
            break
    decision = {
        "contractVersion": CONTRACT_VERSION,
        "profile": REPORT_PROFILE,
        "outcome": "allowed" if allowed else "denied",
        "requestDigest": _digest(req),
        "decidedAt": now,
    }
    if allowed:
        decision["expiresAt"] = now + REPORT_PERMIT_SECONDS
    return _validate("ReportSourceDecision", decision)


def require_report_source_permit(decision: dict | None, *, request: dict, now: int) -> None:
    """Check an authenticated User response for the current Hub attempt only."""
    req = report_source_request(request)
    _validate("PrivateResourceTime", now)
    if decision is None:
        raise ContractError("source_unavailable")
    permit = _validate("ReportSourceDecision", decision)
    if permit["requestDigest"] != _digest(req):
        raise ContractError("recipient_binding_mismatch")
    if permit["decidedAt"] > now:
        raise ContractError("source_unavailable")
    if permit["outcome"] != "allowed":
        raise ContractError("insufficient_scope")
    if not now < permit["expiresAt"] <= permit["decidedAt"] + REPORT_PERMIT_SECONDS:
        raise ContractError("source_unavailable")


def source_index_digest(entries: list[dict]) -> str:
    """Digest the non-terminal source index with stable ordering."""
    if type(entries) is not list or len(entries) > MAX_RESOURCES + 2:
        raise ContractError("malformed_request")
    rows = [_validate("PrivateSourceIndexEntry", item) for item in entries]
    _require_unique_bindings(row["binding"] for row in rows)
    kinds = [row["binding"]["ref"]["kind"] for row in rows]
    if (
        kinds.count("holdings") > MAX_RESOURCES
        or kinds.count("watchlist") > 1
        or kinds.count("channel_follows") > 1
    ):
        raise ContractError("malformed_request")
    return _digest(sorted(rows, key=lambda row: _resource_key(row["binding"])))


def recovery_request_digest(request: dict) -> str:
    return _digest(_validate("PrivateRecoveryRequest", request))


def verify_owner_recovery_evidence(
    evidence: dict | None,
    *,
    request: dict,
    pinned_root_key_id: str,
    now: int,
    previous: dict | None = None,
) -> dict:
    """Check Owner-origin evidence independently of a saved vault response."""
    _validate("PrivateResourceTime", now)
    digest = recovery_request_digest(request)
    if evidence is None:
        raise ContractError("authorization_unavailable")
    value = _validate("PrivateRecoveryEvidence", evidence)
    _scope_match(request, value)
    if value["rootKeyId"] != pinned_root_key_id:
        raise ContractError("untrusted_key")
    if value["requestDigest"] != digest:
        raise ContractError("recipient_binding_mismatch")
    if (
        not value["verifiedAt"]
        <= now
        < value["expiresAt"]
        <= (value["verifiedAt"] + RECOVERY_EVIDENCE_SECONDS)
    ):
        raise ContractError("authorization_unavailable")
    if value["archive"]["state"] != "active" or value["device"] != "active":
        raise ContractError("key_authorization_required")
    current, start = value["registry"], value["registryStart"]
    if (current["registryEpoch"] == 1) != (start is None) or (
        start is not None
        and (
            current["registryEpoch"] != start["registryEpoch"]
            or current["registrySequence"] < start["registrySequence"]
            or current["keyEpoch"] < start["keyEpoch"]
            or (current["registrySequence"] == start["registrySequence"] and current != start)
        )
    ):
        raise ContractError("registry_conflict")
    if previous is not None:
        baseline = _validate("PrivateRecoveryEvidence", previous)
        _scope_match(value, baseline, _ROOT_SCOPE)
        before = baseline["registry"]
        if (
            value["vaultVersion"] < baseline["vaultVersion"]
            or value["archive"]["version"] < baseline["archive"]["version"]
            or any(
                current[field] < before[field]
                for field in ("registryEpoch", "registrySequence", "keyEpoch")
            )
            or (current["registrySequence"] == before["registrySequence"] and current != before)
            or (
                current["registryEpoch"] == before["registryEpoch"]
                and start != baseline["registryStart"]
            )
        ):
            raise ContractError("rollback_detected")
    return value


def _head(registry: VerifiedRegistry, epoch: int) -> dict:
    return {
        "registryEpoch": epoch,
        "registrySequence": registry.registry_sequence,
        "checkpointDigest": registry.checkpoint_digest,
        "keyEpoch": registry.key_epoch,
    }


@dataclass(frozen=True)
class PrivateRegistryCursor:
    """Verified prefix in a specific epoch, which may be short of a target."""

    registry: VerifiedRegistry
    registry_epoch: int

    def head(self) -> dict:
        return _head(self.registry, self.registry_epoch)


def _check_registry_scope(
    registry: VerifiedRegistry, *, owner_subject: str, vault_id: str, root_key_id: str
):
    if (registry.owner_subject, registry.vault_id, registry.root_key_id) != (
        owner_subject,
        vault_id,
        root_key_id,
    ):
        raise ContractError("untrusted_key")


def verify_private_registry_page(
    page: dict,
    *,
    owner_subject: str,
    vault_id: str,
    pinned_root_key_id: str,
    root_jwk: dict,
    trusted_target: dict,
    previous: PrivateRegistryCursor | None,
    now: int,
) -> PrivateRegistryCursor:
    """Read a bounded contiguous page up to a separately authenticated target.

    A caller resuming past genesis supplies the verified previous page (or a
    verified transition head). An intermediate page is never current authority.
    """
    value = _validate("PrivateRegistryPage", page, limit=MAX_REGISTRY_PAGE_BYTES)
    target = _validate("PrivateRegistryHead", trusted_target)
    _scope_match(
        value,
        {"ownerSubject": owner_subject, "vaultId": vault_id, "rootKeyId": pinned_root_key_id},
        _ROOT_SCOPE,
    )
    epoch = target["registryEpoch"]
    if previous is not None:
        _check_registry_scope(
            previous.registry,
            owner_subject=owner_subject,
            vault_id=vault_id,
            root_key_id=pinned_root_key_id,
        )
    if value["target"] != target or value["base"] != (
        None if previous is None else previous.head()
    ):
        raise ContractError("registry_conflict")
    if epoch != (1 if previous is None else previous.registry_epoch):
        raise ContractError("rollback_detected")

    memo = RegistryCertificateMemo()
    registry = previous.registry if previous else None
    for bundle in value["bundles"]:
        expected = 1 if registry is None else registry.registry_sequence + 1
        registry = verify_registry(
            bundle,
            root_jwk=root_jwk,
            pinned_root_key_id=pinned_root_key_id,
            owner_subject=owner_subject,
            vault_id=vault_id,
            now=now,
            previous=registry,
            signature_memo=memo,
        )
        if registry.registry_sequence != expected or expected > target["registrySequence"]:
            raise ContractError("registry_conflict")
    if registry.key_epoch > target["keyEpoch"] or (
        registry.registry_sequence == target["registrySequence"]
        and _head(registry, epoch) != target
    ):
        raise ContractError("registry_conflict")
    return PrivateRegistryCursor(registry, epoch)


def verify_private_registry_transition(
    signed: dict,
    *,
    first_bundle: dict,
    root_jwk: dict,
    owner_subject: str,
    vault_id: str,
    pinned_root_key_id: str,
    authenticated_start: dict,
    now: int,
    previous: PrivateRegistryCursor | None = None,
) -> PrivateRegistryCursor:
    """Read a Root-signed start at an independently authenticated current floor.

    The writer additionally supplies the previous registry and commits the
    signed transition, next bundle, floor, and original receipt atomically.
    """
    _validate("PrivateResourceTime", now)
    change = _validate(
        "PrivateRegistryTransition",
        verify_jws(signed, root_jwk, typ="fv-control+jws", expected_kid=pinned_root_key_id),
    )
    _scope_match(
        change,
        {"ownerSubject": owner_subject, "vaultId": vault_id, "rootKeyId": pinned_root_key_id},
        _ROOT_SCOPE,
    )
    if change["issuedAt"] > now or change["archive"]["state"] != "active":
        raise ContractError("key_authorization_required")
    prior, next_head = change["previousHead"], change["nextHead"]
    if (
        next_head["registryEpoch"] != prior["registryEpoch"] + 1
        or next_head["registrySequence"] != prior["registrySequence"] + 1
        or next_head["keyEpoch"] < prior["keyEpoch"]
        or change["nextVaultVersion"] != change["previousVaultVersion"] + 1
        or next_head != _validate("PrivateRegistryHead", authenticated_start)
    ):
        raise ContractError("rollback_detected")
    registry = verify_registry(
        first_bundle,
        root_jwk=root_jwk,
        pinned_root_key_id=pinned_root_key_id,
        owner_subject=owner_subject,
        vault_id=vault_id,
        now=change["issuedAt"],
    )
    checkpoint = verify_jws(
        first_bundle["checkpoint"], root_jwk, typ="fv-control+jws", expected_kid=pinned_root_key_id
    )
    if (
        checkpoint["previousDigest"] != prior["checkpointDigest"]
        or registry.issued_at != change["issuedAt"]
        or _head(registry, next_head["registryEpoch"]) != next_head
    ):
        raise ContractError("registry_conflict")
    keys = set(change["ownerKeyIds"])
    if registry.active_key_ids != keys or set(registry.certificates) != keys:
        raise ContractError("key_authorization_required")
    certs = {key: registry.cert(key, connection_id=None, now=change["issuedAt"]) for key in keys}
    roles = {cert["role"] for cert in certs.values()}
    if not roles <= _OWNER_ROLES or not {"device_sig", "device_enc", "recovery_enc"} <= roles:
        raise ContractError("key_authorization_required")
    if previous is not None:
        _check_registry_scope(
            previous.registry,
            owner_subject=owner_subject,
            vault_id=vault_id,
            root_key_id=pinned_root_key_id,
        )
        if previous.head() != prior or change["issuedAt"] < previous.registry.issued_at:
            raise ContractError("registry_conflict")
        for key, cert in certs.items():
            if previous.registry.cert(key, connection_id=None, now=change["issuedAt"]) != cert:
                raise ContractError("key_authorization_required")
    return PrivateRegistryCursor(registry, next_head["registryEpoch"])


def validate_history_reference(reference: dict, *, watermark: dict) -> dict:
    """Check a new reference inside the same transaction that advances its barrier."""
    value = _validate("PrivateHistoryReference", reference)
    floor = _validate("PrivateHistoryWatermark", watermark)
    _scope_match(value, floor, (*_ROOT_SCOPE, "registryEpoch"))
    if value["firstSequence"] > value["lastSequence"]:
        raise ContractError("malformed_request")
    if value["firstSequence"] <= floor["committedThroughSequence"]:
        raise ContractError("version_conflict")
    return value


def plan_history_watermark(
    watermark: dict, *, retired_through: int, references: list[dict]
) -> dict:
    """Choose a reclaim boundary using complete live references in one transaction.

    All readers pin before using retired evidence. Reference creation and this
    CAS share the same watermark revision even when the boundary does not move.
    """
    floor = _validate("PrivateHistoryWatermark", watermark)
    _validate("PrivateResourceTime", retired_through)
    existing = floor["committedThroughSequence"]
    if retired_through < existing:
        raise ContractError("version_conflict")
    proposed = retired_through
    for reference in references:
        live = validate_history_reference(reference, watermark=floor)
        proposed = min(proposed, live["firstSequence"] - 1)
    if proposed == existing:
        return floor
    return _validate(
        "PrivateHistoryWatermark",
        {**floor, "committedThroughSequence": proposed, "generation": floor["generation"] + 1},
    )
