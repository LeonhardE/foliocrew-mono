"""Verify the original registry and archive for a transferred User vault."""

from folioview_shared.encrypted.authority import RegistryCertificateMemo, verify_registry
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.legacy_archive import verify_legacy_archive_history
from folioview_shared.encrypted.private_resources import PrivateRegistryCursor

from .legacy_baselines import LegacyVaultBaselines
from .recovery import RecoveryHeads
from .registry_pages import MAX_PAGE_ENTRIES, RegistryHistory


class UserRegistryTransition:
    """Read bounded signed history and verify its original archive anchor."""

    def __init__(self, store):
        self.baselines = LegacyVaultBaselines(store)
        self.history = RegistryHistory(RecoveryHeads(store))

    def original_history(self, baseline, now):
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
        return cursor, state, bundles
