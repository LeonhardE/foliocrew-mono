"""Apply a Root-approved Owner key renewal in the transferred User vault."""

from folioview_shared.encrypted.authority import RegistryCertificateMemo, verify_registry
from folioview_shared.encrypted.constants import MAX_READ_BYTES, MAX_SAFE_INTEGER
from folioview_shared.encrypted.crypto import signing_input_fingerprint
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json
from folioview_shared.encrypted.key_renewal import (
    PROFILE,
    owner_renewal_receipt,
    owner_renewal_response,
    owner_renewal_state,
    require_fresh_renewal_keys,
    verify_owner_renewal_archive,
    verify_owner_renewal_command,
    verify_owner_renewal_delta,
)
from folioview_shared.encrypted.legacy_archive import (
    MAX_LIFECYCLE_OPERATIONS,
    advance_legacy_archive,
    legacy_archive_receipt,
    validate_passkey_archive,
    verify_transferred_archive_history,
)
from folioview_shared.encrypted.private_resources import PrivateRegistryCursor, source_index_digest
from folioview_shared.identity import owner_key

from ..resources import ResourceUnavailable, SQLiteUserResourceStore
from .archive_lifecycle import PrivateArchiveLifecycle
from .authority_cutover import ARCHIVE_RECORDS, HANDOVERS, WITNESSES, _witness
from .legacy_baselines import _sha
from .original_operations import original_key_renewal
from .recovery import COLLECTION as HEADS
from .recovery import build_recovery_head
from .registry_pages import COLLECTION as HISTORY
from .registry_pages import MAX_ENTRY_BYTES, _index
from .source_invalidations import SOURCE_INDEX
from .source_registrations import _MAX_REGISTRY_EXTENSION

RECEIPTS = "user_private_key_renewal_receipts"


def _private_registry(bundle, vault, previous, now, memo=None):
    return verify_registry(
        bundle,
        root_jwk=vault["rootJwk"],
        pinned_root_key_id=vault["rootKeyId"],
        owner_subject=vault["ownerSubject"],
        vault_id=vault["vaultId"],
        previous=previous,
        now=now,
        signature_memo=memo,
    )


def _registries(vault, original_count, now):
    verified = []
    signatures = RegistryCertificateMemo()
    for index, bundle in enumerate(vault["registryHistory"]):
        previous = verified[-1] if index and index != original_count else None
        verified.append(_private_registry(bundle, vault, previous, now, signatures))
    return verified


def _verified_receipt(row, vault, state, history, original_count, operation, *, retained=False):
    if (
        type(row) is not dict
        or row.keys()
        != {
            "profile",
            "ownerSubject",
            "vaultId",
            "rootKeyId",
            "command",
            "archiveCommand",
            "receipt",
        }
        or row["profile"] != PROFILE
        or type(row["receipt"]) is not dict
        or any(row[field] != vault[field] for field in ("ownerSubject", "vaultId", "rootKeyId"))
    ):
        raise ContractError("authorization_unavailable")
    payload = verify_owner_renewal_command(row["command"], vault)
    archive = verify_owner_renewal_archive(payload, row["archiveCommand"], vault)
    position = payload["registrySequence"]
    from_correct_generation = (
        1 <= position < original_count if retained else original_count < position < len(history)
    )
    accepted = row["receipt"].get("acceptedAt")
    archive_item = state["operations"].get(operation)
    if (
        payload["stableOperationId"] != operation
        or not from_correct_generation
        or type(accepted) is not int
        or not payload["issuedAt"] <= accepted < payload["expiresAt"]
        or not archive["issuedAt"] <= accepted < archive["expiresAt"]
        or archive_item is None
        or archive_item["receipt"]["commandFingerprint"] != payload["archiveCommandFingerprint"]
        or archive_item["receipt"]["acceptedAt"] != accepted
    ):
        raise ContractError("authorization_unavailable")
    require_fresh_renewal_keys(payload, history[:position])
    verify_owner_renewal_delta(payload, history[position - 1], history[position], accepted)
    receipt = archive_item["receipt"]
    expected = owner_renewal_receipt(
        vault,
        payload,
        history[position],
        {
            "version": receipt["lifecycleVersion"],
            "revision": receipt["archiveRevision"],
            "digest": receipt["archiveDigest"],
        },
        row["command"],
        accepted,
    )
    if row["receipt"] != expected:
        raise ContractError("authorization_unavailable")
    return expected


class PrivateKeyRenewals(PrivateArchiveLifecycle):
    def __init__(self, store, **options):
        super().__init__(store, **options)
        if isinstance(store, SQLiteUserResourceStore):
            with store.connection() as db:
                db.execute(
                    f"CREATE TABLE IF NOT EXISTS {RECEIPTS} "
                    "(owner TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )

    @staticmethod
    def _receipt_cell(owner, vault, operation):
        return RECEIPTS, _sha(canonical_json([owner, vault, operation]))

    def _saved(self, head, public, operation):
        owner, vault = public["ownerSubject"], public["vaultId"]
        receipt = self._receipt_cell(owner, vault, operation)
        row = self.cutover._read((receipt,))[0]
        if row is not None:
            return row, False
        witness, installed = self.cutover._read(((WITNESSES, owner), (HANDOVERS, owner)))
        proof = _witness(witness, owner, vault)
        self.cutover._installed(installed, head, owner, vault)
        if (
            proof.rootKeyId != public["rootKeyId"]
            or proof.baselineDigest != head["handover"]["baselineDigest"]
            or installed["freezeId"] != proof.freezeId
        ):
            raise ContractError("authorization_unavailable")
        original = self.cutover.verifier.baselines.read(owner, vault, proof.operationsDigest)
        if original is None:
            raise ContractError("authorization_unavailable")
        return original_key_renewal(public, original, operation), True

    def overview(self, uid, vault):
        now = int(self.clock())
        _, _, public, cursor, state, _, _ = self._snapshot(uid, vault, now)
        return owner_renewal_state(public, cursor.registry, state, now)

    def receipt(self, uid, vault, operation):
        now = int(self.clock())
        head, _, public, _, state, _, original = self._snapshot(uid, vault, now)
        row, retained = self._saved(head, public, operation)
        if row is None:
            raise ContractError("not_found")
        return owner_renewal_response(
            _verified_receipt(
                row,
                public,
                state,
                _registries(public, len(original), now),
                len(original),
                operation,
                retained=retained,
            )
        )

    def renew(self, uid, vault, operation, control, archive_control, replacement, bundle):
        owner = owner_key(uid)
        now = int(self.clock())
        head, record, public, cursor, state, lifecycle, original = self._snapshot(uid, vault, now)
        payload = verify_owner_renewal_command(control, public)
        archive_command = verify_owner_renewal_archive(payload, archive_control, public)
        if payload["stableOperationId"] != operation:
            raise ContractError("idempotency_conflict")
        validate_passkey_archive(replacement, owner=owner, vault=vault, root=public["rootKeyId"])
        if _sha(canonical_json(replacement)) != payload["newArchiveDigest"]:
            raise ContractError("recipient_binding_mismatch")
        history = _registries(public, len(original), now)
        receipt_cell = self._receipt_cell(owner, vault, operation)
        row, retained = self._saved(head, public, operation)
        if row is not None:
            receipt = _verified_receipt(
                row, public, state, history, len(original), operation, retained=retained
            )
            if receipt["commandFingerprint"] != signing_input_fingerprint(control) or receipt[
                "archiveCommandFingerprint"
            ] != signing_input_fingerprint(archive_control):
                raise ContractError("idempotency_conflict")
            prior = history[payload["registrySequence"] - 1]
            candidate = _private_registry(bundle, public, prior, now)
            verify_owner_renewal_delta(payload, prior, candidate, receipt["acceptedAt"])
            return owner_renewal_response(receipt)
        if operation in state["operations"]:
            raise ContractError("idempotency_conflict")
        if (
            public["version"] != payload["expectedVaultVersion"]
            or public["version"] >= MAX_SAFE_INTEGER
        ):
            raise ContractError("version_conflict")
        if state["pending"] is not None or state["deleted"]:
            raise ContractError("key_authorization_required")
        current = cursor.registry
        new = _private_registry(bundle, public, current, now)
        require_fresh_renewal_keys(payload, history)
        verify_owner_renewal_delta(payload, current, new, now)
        tail = public["registryHistory"][len(original) :]
        if len(tail) > _MAX_REGISTRY_EXTENSION or state["version"] >= MAX_LIFECYCLE_OPERATIONS:
            raise ContractError("version_conflict")
        if len(canonical_json([*tail, bundle])) > MAX_READ_BYTES - 65_536:
            raise ContractError("payload_too_large")
        existing = public["archive"]
        if any(replacement[key] != existing[key] for key in ("credentialId", "prfSalt")) or any(
            replacement[key] == existing[key] for key in ("iv", "ciphertext")
        ):
            raise ContractError("recipient_binding_mismatch")
        next_cursor = PrivateRegistryCursor(new, cursor.registry_epoch)
        indexed = (HISTORY, _index(owner, vault, next_cursor.registry_epoch, new.registry_sequence))
        entry = {"head": next_cursor.head(), "bundle": bundle, "rootJwk": public["rootJwk"]}
        if len(canonical_json(entry)) > MAX_ENTRY_BYTES:
            raise ContractError("payload_too_large")
        current_cells = ((HEADS, owner), (ARCHIVE_RECORDS, owner))
        after = {
            **public,
            "version": public["version"] + 1,
            "archive": replacement,
            "registryHistory": [*public["registryHistory"], bundle],
        }

        def commit(read, write):
            current_head, current_archive, source, occupied, previous = read(
                (*current_cells, (SOURCE_INDEX, owner), indexed, receipt_cell)
            )
            if (
                [current_head, current_archive] != [head, record]
                or occupied is not None
                or previous is not None
            ):
                raise ContractError("version_conflict")
            if (
                type(source) is not dict
                or source.keys() != {"ownerSubject", "vaultId", "entries"}
                or (source["ownerSubject"], source["vaultId"]) != (owner, vault)
                or source_index_digest(source["entries"]) != head["sourcesDigest"]
            ):
                raise ContractError("source_unavailable")
            accepted = int(self.clock())
            if not now <= accepted or not payload["issuedAt"] <= accepted < payload["expiresAt"]:
                raise ContractError("key_authorization_required")
            verify_owner_renewal_delta(payload, current, new, accepted)
            advanced = advance_legacy_archive(state, archive_command, archive_control, accepted)
            archive_receipt = legacy_archive_receipt(
                public, archive_command, advanced, archive_control, accepted
            )
            next_lifecycle = {
                "ownerSubject": owner,
                "vaultId": vault,
                "rootKeyId": public["rootKeyId"],
                "initialArchiveDigest": state["digest"]
                if lifecycle is None
                else lifecycle["initialArchiveDigest"],
                "history": [
                    *([] if lifecycle is None else lifecycle["history"]),
                    {"command": archive_control, "receipt": archive_receipt},
                ],
            }
            verify_transferred_archive_history(after, next_cursor, next_lifecycle)
            projection = build_recovery_head(
                cursor=next_cursor,
                registry_start=head["registryStart"],
                vault_version=after["version"],
                archive=self._boundary(advanced),
                sources=source["entries"],
                now=accepted,
            )
            if not projection["devices"]:
                raise ContractError("key_authorization_required")
            receipt = owner_renewal_receipt(public, payload, new, advanced, control, accepted)
            write(
                {
                    current_cells[0]: {**projection, "handover": head["handover"]},
                    current_cells[1]: {
                        "archive": replacement,
                        "lifecycle": next_lifecycle,
                        "baselineDigest": head["handover"]["baselineDigest"],
                    },
                    indexed: entry,
                    receipt_cell: {
                        "profile": PROFILE,
                        "ownerSubject": owner,
                        "vaultId": vault,
                        "rootKeyId": public["rootKeyId"],
                        "command": control,
                        "archiveCommand": archive_control,
                        "receipt": receipt,
                    },
                }
            )
            return owner_renewal_response(receipt)

        try:
            replaced = current_cells if record is not None else current_cells[:1]
            return self.cutover._transaction(commit, writes=True, replace=replaced)
        except ResourceUnavailable as error:
            if isinstance(error.__cause__, ContractError):
                raise error.__cause__ from None
            raise ContractError("authorization_unavailable") from None
