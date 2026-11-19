"""Verify an Owner-signed start against the original User migration baseline."""

from dataclasses import dataclass

from folioview_shared.encrypted.authority import RegistryCertificateMemo, verify_registry
from folioview_shared.encrypted.constants import MAX_REGISTRY_BYTES
from folioview_shared.encrypted.crypto import signing_input_fingerprint, verify_jws
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json, strict_json_loads
from folioview_shared.encrypted.legacy_archive import verify_legacy_archive_history
from folioview_shared.encrypted.private_resources import (
    PrivateRegistryCursor,
    verify_private_registry_transition,
)
from folioview_shared.encrypted.schema import validate_schema
from folioview_shared.identity import owner_key

from .legacy_baselines import LegacyVaultBaselines
from .recovery import RecoveryHeads
from .registry_pages import MAX_PAGE_ENTRIES, RegistryHistory

MAX_TRANSITION_PACKET_BYTES = MAX_REGISTRY_BYTES + 16_384


def transition_packet(packet):
    if type(packet) is not dict or packet.keys() != {
        "operationId",
        "signedTransition",
        "firstBundle",
    }:
        raise ContractError("malformed_request")
    raw = canonical_json(packet)
    if len(raw) > MAX_TRANSITION_PACKET_BYTES:
        raise ContractError("payload_too_large")
    packet = strict_json_loads(raw, max_bytes=MAX_TRANSITION_PACKET_BYTES)
    validate_schema("OperationIdentifier", packet["operationId"])
    return packet


@dataclass(frozen=True)
class VerifiedTransition:
    receipt: dict
    original: dict
    start: PrivateRegistryCursor


class UserRegistryTransition:
    """Validate the candidate. The cutover transaction must also check the Hub writer drain."""

    def __init__(self, store):
        self.baselines = LegacyVaultBaselines(store)
        self.history = RegistryHistory(RecoveryHeads(store))

    def _previous(self, baseline, now):
        scope = {key: baseline[key] for key in ("ownerSubject", "vaultId", "rootKeyId")}
        head = baseline["registry"]
        sequence = head["registrySequence"]
        if head["registryEpoch"] != 1 or type(sequence) is not int or not 1 <= sequence <= 32:
            raise ContractError("registry_conflict")
        previous, bundles = None, []
        memo = RegistryCertificateMemo()
        for first in range(1, sequence + 1, MAX_PAGE_ENTRIES):
            count = range(first, min(sequence + 1, first + MAX_PAGE_ENTRIES))
            entries = self.history._read(scope, 1, list(count))
            for number, entry in zip(count, entries, strict=True):
                bundle = entry["bundle"]
                previous = verify_registry(
                    bundle,
                    root_jwk=baseline["rootJwk"],
                    pinned_root_key_id=baseline["rootKeyId"],
                    owner_subject=baseline["ownerSubject"],
                    vault_id=baseline["vaultId"],
                    now=now,
                    previous=previous,
                    signature_memo=memo,
                )
                if previous.registry_sequence != number:
                    raise ContractError("registry_conflict")
                bundles.append(bundle)
        cursor = PrivateRegistryCursor(previous, 1)
        if cursor.head() != head:
            raise ContractError("registry_conflict")
        legacy = {**baseline, "registryHistory": bundles}
        state = verify_legacy_archive_history(legacy, previous, baseline["archiveLifecycle"])
        archive = baseline["archiveBoundary"]
        if (
            state["deleted"]
            or state["pending"] is not None
            or archive
            != {
                "state": "active",
                "version": state["version"] + 1,
                "digest": state["digest"],
            }
        ):
            raise ContractError("key_authorization_required")
        return cursor

    def verify_candidate(self, uid, vault, baseline_digest, packet, *, now):
        return self.prepare(uid, vault, baseline_digest, transition_packet(packet), now=now).receipt

    def prepare(self, uid, vault, baseline_digest, packet, *, now):
        owner = owner_key(uid)
        base = self.baselines.read(owner, vault, baseline_digest)
        if base is None:
            raise ContractError("not_found")
        baseline = strict_json_loads(base)
        if "archiveLifecycle" not in baseline or "registry" not in baseline:
            raise ContractError("not_found")
        signed = packet["signedTransition"]
        change = verify_jws(
            signed,
            baseline["rootJwk"],
            typ="fv-control+jws",
            expected_kid=baseline["rootKeyId"],
        )
        if (
            change.get("operationId") != packet["operationId"]
            or change.get("previousVaultVersion") != baseline["version"]
            or change.get("previousHead") != baseline["registry"]
            or change.get("archive") != baseline["archiveBoundary"]
        ):
            raise ContractError("version_conflict")
        previous = self._previous(baseline, now)
        start = verify_private_registry_transition(
            signed,
            first_bundle=packet["firstBundle"],
            root_jwk=baseline["rootJwk"],
            owner_subject=owner,
            vault_id=vault,
            pinned_root_key_id=baseline["rootKeyId"],
            authenticated_start=change.get("nextHead"),
            previous=previous,
            now=now,
        )
        receipt = {
            "ownerSubject": owner,
            "vaultId": vault,
            "baselineDigest": baseline_digest,
            "operationId": packet["operationId"],
            "transitionFingerprint": signing_input_fingerprint(signed),
            "nextVaultVersion": change["nextVaultVersion"],
            "registryStart": start.head(),
        }
        return VerifiedTransition(receipt, baseline, start)
