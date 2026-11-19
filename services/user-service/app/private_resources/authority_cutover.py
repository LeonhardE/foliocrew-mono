"""Install the first User authority from a frozen, account-scoped Hub witness."""

import os
from typing import Literal

from google.cloud import firestore
from pydantic import ValidationError

from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json, strict_json_loads
from folioview_shared.encrypted.private_resources import (
    MAX_REGISTRY_PAGE_BYTES,
    verify_private_registry_transition,
)
from folioview_shared.encrypted.schema import validate_schema
from folioview_shared.firestore import BoundedTransaction
from folioview_shared.identity import owner_key

from ..firestore_reads import read_documents
from ..resources import FirestoreUserResourceStore, ResourceUnavailable, SQLiteUserResourceStore
from .legacy_baselines import _sha
from .original_operations import original_fence_receipts
from .recovery import COLLECTION as HEADS
from .recovery import (
    ClosedModel,
    CurrentHead,
    Digest,
    EpochSeconds,
    Identifier,
    KeyId,
    OperationId,
    RegistryHead,
    Version,
    build_recovery_head,
)
from .registry_pages import COLLECTION as HISTORY
from .registry_pages import MAX_ENTRY_BYTES, _index
from .registry_transition import UserRegistryTransition, transition_packet
from .report_sources import HOLDINGS_FENCES, HoldingsFence, holdings_fence_key
from .source_invalidations import INVALIDATION_RECEIPTS, SOURCE_INDEX

WITNESSES = "user_private_handover_witnesses"
HANDOVERS = "user_private_handover_receipts"
ARCHIVE_RECORDS = "user_private_archive_records"
_BYTES_FIELDS = {HEADS: "view", HISTORY: "entry", HANDOVERS: "record", ARCHIVE_RECORDS: "record"}


class FrozenScope(ClosedModel):
    ownerSubject: Digest
    vaultId: Identifier
    rootKeyId: KeyId
    freezeId: OperationId
    writerEpoch: Literal[2]
    baselineDigest: Digest
    operationsDigest: Digest
    tombstonesDigest: Digest
    activeLegacyAgents: EpochSeconds
    unsettledLegacyOperations: EpochSeconds


class CutoverReceipt(ClosedModel):
    ownerSubject: Digest
    vaultId: Identifier
    baselineDigest: Digest
    rootKeyId: KeyId
    operationId: OperationId
    transitionFingerprint: Digest
    nextVaultVersion: Version
    registryStart: RegistryHead
    writerEpoch: Literal[2]


def _witness(raw, owner, vault):
    if raw is None:
        raise ContractError("source_unavailable")
    try:
        value = FrozenScope.model_validate(raw)
    except ValidationError:
        raise ContractError("authorization_unavailable") from None
    if (
        (value.ownerSubject, value.vaultId) != (owner, vault)
        or value.activeLegacyAgents
        or value.unsettledLegacyOperations
    ):
        raise ContractError("source_unavailable")
    return value


def _restore_terminal_state(rows, original, restored, expected_digest):
    terminal = [HoldingsFence.model_validate(row).model_dump() for row in rows]
    if _sha(canonical_json(terminal)) != expected_digest:
        raise ContractError("version_conflict")
    for anchor, fence in zip(original["sources"], terminal, strict=True):
        binding = fence["binding"]
        if (
            (fence["ownerSubject"], fence["vaultId"])
            != (original["ownerSubject"], original["vaultId"])
            or binding["ref"] != anchor["resourceRef"]
            or fence["state"] != "deleted"
            or fence["currentRevision"] != 0
            or not any(
                row["request"]["ref"] == binding["ref"]
                and row["request"]["reason"] == "deleted"
                and row["ack"]["acknowledgedSourceEpoch"] == binding["sourceEpoch"]
                for row in restored.values()
            )
        ):
            raise ContractError("source_unavailable")


class UserAuthorityCutover:
    """An existing Hub freeze must precede installation for the cleaned account.

    A trusted cutover controller owns the witness. Browser submissions supply
    only a same-root signed transition and cannot create or replace that proof.
    """

    def __init__(self, store):
        self.store = store
        self.verifier = UserRegistryTransition(store)
        if isinstance(store, SQLiteUserResourceStore):
            with store.connection() as db:
                for collection in (
                    WITNESSES,
                    HANDOVERS,
                    SOURCE_INDEX,
                    INVALIDATION_RECEIPTS,
                    HOLDINGS_FENCES,
                ):
                    db.execute(
                        f"CREATE TABLE IF NOT EXISTS {collection} "
                        "(owner TEXT PRIMARY KEY, value TEXT NOT NULL)"
                    )

    def _named_store(self):
        if not isinstance(self.store, (SQLiteUserResourceStore, FirestoreUserResourceStore)):
            raise ContractError("authorization_unavailable")
        if isinstance(self.store, FirestoreUserResourceStore):
            if self.store.client._database != "user-data":
                raise ContractError("authorization_unavailable")
        elif "K_SERVICE" in os.environ:
            raise ContractError("authorization_unavailable")

    def preflight(self, uid, vault, *, now):
        self._named_store()
        owner = owner_key(uid)
        witness, previous, live = self._read(
            ((WITNESSES, owner), (HANDOVERS, owner), (HEADS, owner))
        )
        if previous is not None:
            receipt, head = self._installed(previous, live, owner, vault)
            return {
                "contractVersion": CONTRACT_VERSION,
                "status": "installed",
                "vaultId": vault,
                "rootKeyId": head.rootKeyId,
                "operationId": receipt.operationId,
            }
        if live is not None:
            raise ContractError("version_conflict")
        proof = _witness(witness, owner, vault)
        original = self.verifier.baselines.read(owner, vault, proof.baselineDigest)
        operations = self.verifier.baselines.read(owner, vault, proof.operationsDigest)
        if original is None or operations is None:
            raise ContractError("source_unavailable")
        source = strict_json_loads(original)
        if source["rootKeyId"] != proof.rootKeyId:
            raise ContractError("version_conflict")
        self.verifier._previous(source, now)
        receipts = original_fence_receipts(source, operations)
        _restore_terminal_state(
            self._read(self._tombstone_cells(source)), source, receipts, proof.tombstonesDigest
        )
        return {
            "contractVersion": CONTRACT_VERSION,
            "status": "ready",
            "vaultId": vault,
            "rootKeyId": proof.rootKeyId,
            "vaultVersion": source["version"],
        }

    @staticmethod
    def _tombstone_cells(original):
        return tuple(
            (
                HOLDINGS_FENCES,
                holdings_fence_key(
                    original["ownerSubject"],
                    original["vaultId"],
                    anchor["resourceRef"]["resourceId"],
                ),
            )
            for anchor in original["sources"]
        )

    def install(self, uid, vault, body, *, now):
        self._named_store()
        packet = transition_packet(body)
        owner, packet_digest = owner_key(uid), _sha(canonical_json(packet))
        lock, last, current = (WITNESSES, owner), (HANDOVERS, owner), (HEADS, owner)
        try:
            witness, previous, head = self._read((lock, last, current))
            if previous is not None:
                return self._replay(previous, head, owner, vault, packet_digest)
            if head is not None:
                raise ContractError("version_conflict")
            proof = _witness(witness, owner, vault)
            candidate = self.verifier.prepare(uid, vault, proof.baselineDigest, packet, now=now)
            original = candidate.original
            if proof.rootKeyId != original["rootKeyId"]:
                raise ContractError("version_conflict")
            operations = self.verifier.baselines.read(owner, vault, proof.operationsDigest)
            if operations is None:
                raise ContractError("source_unavailable")
            original_receipts = original_fence_receipts(original, operations)
            next_start = candidate.start.head()
            recovery = build_recovery_head(
                cursor=candidate.start,
                registry_start=next_start,
                vault_version=candidate.receipt["nextVaultVersion"],
                archive=original["archiveBoundary"],
                sources=[],
                now=now,
            )
            if not recovery["devices"]:
                raise ContractError("key_authorization_required")
            recovery["handover"] = {
                "operationId": packet["operationId"],
                "baselineDigest": proof.baselineDigest,
                "writerEpoch": proof.writerEpoch,
            }
            receipt = CutoverReceipt.model_validate(
                {
                    **candidate.receipt,
                    "rootKeyId": proof.rootKeyId,
                    "writerEpoch": proof.writerEpoch,
                }
            ).model_dump()
            first = {
                "head": next_start,
                "bundle": packet["firstBundle"],
                "rootJwk": original["rootJwk"],
            }
            if len(canonical_json(first)) > MAX_ENTRY_BYTES:
                raise ContractError("payload_too_large")
            entry_key = _index(
                owner, vault, next_start["registryEpoch"], next_start["registrySequence"]
            )
            tombstones = self._tombstone_cells(original)
            created = {
                current: recovery,
                last: {
                    "packetDigest": packet_digest,
                    "freezeId": proof.freezeId,
                    "signedTransition": packet["signedTransition"],
                    "receipt": receipt,
                },
                (HISTORY, entry_key): first,
                (SOURCE_INDEX, owner): {"ownerSubject": owner, "vaultId": vault, "entries": []},
                **{(INVALIDATION_RECEIPTS, key): row for key, row in original_receipts.items()},
            }

            def commit(read, create):
                fresh, prior, live = read((lock, last, current))
                if prior is not None:
                    return self._replay(prior, live, owner, vault, packet_digest)
                if fresh != witness or live is not None:
                    raise ContractError("version_conflict")
                _restore_terminal_state(
                    read(tombstones), original, original_receipts, proof.tombstonesDigest
                )
                untouched = tuple(cell for cell in created if cell not in (last, current))
                if any(row is not None for row in read(untouched)):
                    raise ContractError("version_conflict")
                create(created)
                return receipt

            return self._transaction(commit, writes=True)
        except ContractError:
            raise
        except ResourceUnavailable as error:
            if isinstance(error.__cause__, ContractError):
                raise error.__cause__ from None
            raise ContractError("authorization_unavailable") from None
        except (ValidationError, ValueError):
            raise ContractError("authorization_unavailable") from None

    def read_start(self, uid, vault, nonce, *, now):
        validate_schema("OperationIdentifier", nonce)
        self._named_store()
        owner = owner_key(uid)

        def snapshot(read, _create):
            stored, raw_head = read(((HANDOVERS, owner), (HEADS, owner)))
            if stored is None or raw_head is None:
                raise ContractError("not_found")
            receipt, head = self._installed(stored, raw_head, owner, vault)
            if head.archive.state != "active":
                raise ContractError("key_authorization_required")
            first = receipt.registryStart.model_dump()
            key = _index(owner, vault, first["registryEpoch"], first["registrySequence"])
            entry = read(((HISTORY, key),))[0]
            if (
                entry is None
                or entry.keys() != {"head", "bundle", "rootJwk"}
                or entry["head"] != first
            ):
                raise ContractError("authorization_unavailable")
            accepted = verify_private_registry_transition(
                stored["signedTransition"],
                first_bundle=entry["bundle"],
                root_jwk=entry["rootJwk"],
                owner_subject=owner,
                vault_id=vault,
                pinned_root_key_id=head.rootKeyId,
                authenticated_start=first,
                previous=None,
                now=now,
            )
            if accepted.head() != first:
                raise ContractError("registry_conflict")
            reply = {
                "contractVersion": CONTRACT_VERSION,
                "profile": "folioview.owner-registry-start-evidence.v1",
                "nonce": nonce,
                "ownerSubject": owner,
                "vaultId": vault,
                "rootKeyId": head.rootKeyId,
                "vaultVersion": head.vaultVersion,
                "archive": head.archive.model_dump(),
                "registry": head.registry.model_dump(),
                "registryStart": first,
                "sourcesDigest": head.sourcesDigest,
                "rootJwk": entry["rootJwk"],
                "signedTransition": stored["signedTransition"],
                "firstBundle": entry["bundle"],
            }
            if len(canonical_json(reply)) > MAX_REGISTRY_PAGE_BYTES:
                raise ContractError("payload_too_large")
            return reply

        try:
            return self._transaction(snapshot, writes=False)
        except ContractError:
            raise
        except ResourceUnavailable as error:
            if isinstance(error.__cause__, ContractError):
                raise error.__cause__ from None
            raise ContractError("authorization_unavailable") from None
        except (ValidationError, ValueError):
            raise ContractError("authorization_unavailable") from None

    @classmethod
    def _replay(cls, saved, head, owner, vault, digest):
        receipt, _ = cls._installed(saved, head, owner, vault)
        if saved["packetDigest"] != digest:
            raise ContractError("idempotency_conflict")
        return receipt.model_dump()

    @staticmethod
    def _installed(saved, head, owner, vault):
        if (
            type(saved) is not dict
            or saved.keys() != {"packetDigest", "freezeId", "signedTransition", "receipt"}
            or type(saved["receipt"]) is not dict
        ):
            raise ContractError("authorization_unavailable")
        receipt = CutoverReceipt.model_validate(saved["receipt"])
        live = CurrentHead.model_validate(head)
        handover = live.handover
        if (
            (receipt.ownerSubject, receipt.vaultId) != (owner, vault)
            or (live.ownerSubject, live.vaultId) != (owner, vault)
            or live.rootKeyId != receipt.rootKeyId
            or handover is None
            or handover.operationId != receipt.operationId
            or handover.baselineDigest != receipt.baselineDigest
            or handover.writerEpoch != receipt.writerEpoch
            or live.registry.registryEpoch < receipt.registryStart.registryEpoch
            or live.vaultVersion < receipt.nextVaultVersion
        ):
            raise ContractError("version_conflict")
        return receipt, live

    def _read(self, cells):
        if isinstance(self.store, SQLiteUserResourceStore):
            with self.store.connection() as db:
                return self._read_sqlite(db, cells)
        return self._read_firestore(None, cells)

    @staticmethod
    def _read_sqlite(db, cells):
        values = []
        for table, key in cells:
            column = "entry" if table == HISTORY else "owner"
            row = db.execute(f"SELECT value FROM {table} WHERE {column}=?", (key,)).fetchone()
            values.append(strict_json_loads(row[0]) if row else None)
        return values

    def _references(self, cells):
        return [self.store.client.collection(table).document(key) for table, key in cells]

    def _read_firestore(self, txn, cells):
        values = []
        for start in range(0, len(cells), 13):
            chunk = cells[start : start + 13]
            rows = read_documents(self.store.client, txn, self._references(chunk), maximum=13)
            for (table, _), row in zip(chunk, rows, strict=True):
                field = _BYTES_FIELDS.get(table)
                if row is not None and field is not None:
                    if row.keys() != {field} or type(row[field]) is not bytes:
                        raise ContractError("authorization_unavailable")
                    row = strict_json_loads(row[field])
                values.append(row)
        return values

    def _transaction(self, callback, *, writes, replace=()):
        if isinstance(self.store, SQLiteUserResourceStore):
            with self.store.connection() as db:
                db.execute("BEGIN IMMEDIATE" if writes else "BEGIN")

                def create(values):
                    for (table, key), value in values.items():
                        if (table, key) in replace:
                            changed = db.execute(
                                f"UPDATE {table} SET value=? WHERE owner=?",
                                (canonical_json(value).decode(), key),
                            )
                            if changed.rowcount != 1:
                                raise ContractError("version_conflict")
                            continue
                        db.execute(
                            f"INSERT INTO {table} VALUES (?, ?)",
                            (key, canonical_json(value).decode()),
                        )

                return callback(lambda cells: self._read_sqlite(db, cells), create)

        @firestore.transactional
        def run(transaction):
            def create(values):
                for cell, ref in zip(values, self._references(values), strict=True):
                    field = _BYTES_FIELDS.get(cell[0])
                    body = values[cell]
                    write = transaction.update if cell in replace else transaction.create
                    write(ref, {field: canonical_json(body)} if field else body)

            return callback(lambda cells: self._read_firestore(transaction, cells), create)

        return run(BoundedTransaction(self.store.client, max_attempts=3))
