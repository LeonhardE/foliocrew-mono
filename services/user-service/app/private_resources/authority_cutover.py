"""Read and verify the committed User vault authority and recorded migration proof."""

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
)
from .registry_pages import COLLECTION as HISTORY
from .registry_pages import _index
from .registry_transition import UserRegistryTransition
from .report_sources import HOLDINGS_FENCES
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


class UserAuthorityCutover:
    """Access the signed registry start retained by the completed authority transfer."""

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

    def read_start(self, uid, vault, nonce, *, now, allow_deleted=False):
        validate_schema("OperationIdentifier", nonce)
        self._named_store()
        owner = owner_key(uid)

        def snapshot(read, _create):
            stored, raw_head = read(((HANDOVERS, owner), (HEADS, owner)))
            if stored is None or raw_head is None:
                raise ContractError("not_found")
            receipt, head = self._installed(stored, raw_head, owner, vault)
            if head.archive.state != "active" and not (
                allow_deleted and head.archive.state == "deleted"
            ):
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
