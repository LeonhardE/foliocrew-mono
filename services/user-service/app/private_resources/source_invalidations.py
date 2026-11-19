"""Commit Portfolio invalidations and exact receipts under the User writer."""

import math
import time
from datetime import UTC, datetime
from typing import Literal

from google.cloud import firestore
from pydantic import ValidationError

from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json
from folioview_shared.encrypted.private_resources import source_index_digest
from folioview_shared.encrypted.schema import validate_schema
from folioview_shared.firestore import BoundedTransaction

from ..firestore_reads import read_documents
from ..resources import FirestoreUserResourceStore, ResourceUnavailable, SQLiteUserResourceStore
from .legacy_baselines import _sha
from .recovery import COLLECTION as HEADS
from .recovery import ClosedModel, Digest, RecoveryHeads, Version
from .report_sources import HOLDINGS_FENCES, HoldingsFence, HoldingsRef, holdings_fence_key

SOURCE_INDEX = "user_private_source_indexes"
INVALIDATION_RECEIPTS = "user_private_source_invalidation_receipts"
_RESULTS = {
    "account_scope_changed": ("eligible", "active", 2),
    "disconnected": ("disconnected", "disconnected", 1),
    "deleted": ("deleted", None, 0),
}
_MAX_MUTATIONS = 128


class PortfolioInvalidation(ClosedModel):
    contractVersion: Literal[CONTRACT_VERSION]
    ownerSubject: Digest
    mutationId: str
    ref: HoldingsRef
    expectedSourceEpoch: Version
    newSourceEpoch: Version
    reason: Literal["account_scope_changed", "disconnected", "deleted"]


def _request(value):
    try:
        packet = PortfolioInvalidation.model_validate(value).model_dump()
        validate_schema("OperationIdentifier", packet["mutationId"])
        if packet["newSourceEpoch"] != packet["expectedSourceEpoch"] + 1:
            raise ValueError
    except (ContractError, ValueError):
        raise ContractError("malformed_request") from None
    return packet


def invalidation_receipt_key(owner, operation):
    return _sha(canonical_json([owner, "portfolio", operation]))


def _ack(request, at):
    return {
        "contractVersion": CONTRACT_VERSION,
        "mutationId": request["mutationId"],
        "ref": request["ref"],
        "acknowledgedSourceEpoch": request["newSourceEpoch"],
        "acknowledgedAt": at,
    }


def _replay(saved, owner, vault, request):
    try:
        original = _request(saved["request"])
        ack = saved["ack"]
        at = ack["acknowledgedAt"]
        if (
            saved.keys() != {"ownerSubject", "vaultId", "request", "fingerprint", "ack"}
            or saved["ownerSubject"] != owner
            or saved["vaultId"] != vault
            or original["ownerSubject"] != owner
            or original["mutationId"] != request["mutationId"]
            or saved["fingerprint"] != _sha(canonical_json(original))
            or canonical_json(original) != canonical_json(saved["request"])
            or type(ack["acknowledgedSourceEpoch"]) is not int
            or not at.endswith("Z")
            or ack != _ack(original, at)
        ):
            raise ValueError
        datetime.fromisoformat(at.replace("Z", "+00:00"))
    except (AttributeError, ContractError, KeyError, TypeError, ValueError):
        raise ContractError("authorization_unavailable") from None
    if original != request:
        raise ContractError("idempotency_conflict")
    return ack


def _change_index(row, head, fence, next_binding, state):
    if type(row) is not dict or row.keys() != {"ownerSubject", "vaultId", "entries"}:
        raise ContractError("source_unavailable")
    entries = row["entries"]
    if (
        row["ownerSubject"] != head["ownerSubject"]
        or row["vaultId"] != head["vaultId"]
        or source_index_digest(entries) != head["sourcesDigest"]
    ):
        raise ContractError("source_unavailable")
    previous_state = {"eligible": "active", "revoking": "revoking", "disconnected": "disconnected"}
    original = {"binding": fence["binding"], "state": previous_state[fence["state"]]}
    if original not in entries:
        raise ContractError("source_unavailable")
    following = [item for item in entries if item != original]
    if state is not None:
        following.append({"binding": next_binding, "state": state})
    return {**row, "entries": following}, source_index_digest(following)


class SourceInvalidations:
    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock
        self.heads = RecoveryHeads(store)
        if isinstance(store, SQLiteUserResourceStore):
            with store.connection() as db:
                for collection in (SOURCE_INDEX, HOLDINGS_FENCES, INVALIDATION_RECEIPTS):
                    db.execute(
                        f"CREATE TABLE IF NOT EXISTS {collection} "
                        "(owner TEXT PRIMARY KEY, value TEXT NOT NULL)"
                    )

    def invalidate(self, value):
        request = _request(value)
        owner = request["ownerSubject"]
        receipt_key = invalidation_receipt_key(owner, request["mutationId"])
        try:
            if isinstance(self.store, SQLiteUserResourceStore):
                return self._sqlite(owner, receipt_key, request)
            if isinstance(self.store, FirestoreUserResourceStore):
                return self._firestore(owner, receipt_key, request)
        except ContractError:
            raise
        except ResourceUnavailable as error:
            if isinstance(error.__cause__, ContractError):
                raise error.__cause__ from None
        except (ValidationError, ValueError, OverflowError, OSError):
            pass
        raise ContractError("authorization_unavailable")

    def _plan(self, head, saved, index, raw_fence, request):
        owner, vault = request["ownerSubject"], head["vaultId"]
        if saved is not None:
            return _replay(saved, owner, vault, request), None
        if raw_fence is None:
            raise ContractError("source_unavailable")
        fence = HoldingsFence.model_validate(raw_fence).model_dump()
        state, index_state, reserve = _RESULTS[request["reason"]]
        previous_epoch = request["expectedSourceEpoch"]
        if (
            fence["ownerSubject"] != owner
            or fence["vaultId"] != vault
            or fence["binding"] != {"ref": request["ref"], "sourceEpoch": previous_epoch}
            or fence["state"] == "deleted"
            or (fence["state"] == "disconnected" and state != "deleted")
            or previous_epoch > _MAX_MUTATIONS - reserve
        ):
            raise ContractError("version_conflict")
        binding = {"ref": request["ref"], "sourceEpoch": request["newSourceEpoch"]}
        index, digest = _change_index(index, head, fence, binding, index_state)
        next_fence = {**fence, "binding": binding, "state": state, "currentRevision": 0}
        now = self.clock()
        if type(now) not in (int, float) or not math.isfinite(now) or not 0 <= now <= 253402300799:
            raise ContractError("authorization_unavailable")
        ack = _ack(request, datetime.fromtimestamp(now, UTC).isoformat().replace("+00:00", "Z"))
        receipt = {
            "ownerSubject": owner,
            "vaultId": vault,
            "request": request,
            "fingerprint": _sha(canonical_json(request)),
            "ack": ack,
        }
        return ack, ({**head, "sourcesDigest": digest}, receipt, index, next_fence)

    @staticmethod
    def _keys(owner, receipt_key, head, request):
        # Resolve the vault from the current authority, never from Portfolio input.
        if head is None or head["ownerSubject"] != owner or head.get("handover") is None:
            raise ContractError("source_unavailable")
        fence = holdings_fence_key(owner, head["vaultId"], request["ref"]["resourceId"])
        return (
            (INVALIDATION_RECEIPTS, receipt_key),
            (SOURCE_INDEX, owner),
            (HOLDINGS_FENCES, fence),
        )

    def _sqlite(self, owner, receipt_key, request):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            head = self.heads._decode(self.heads._local(db, owner))
            keys = self._keys(owner, receipt_key, head, request)
            saved = self.store.value(db, *keys[0])
            rows = (
                (None, None)
                if saved is not None
                else tuple(self.store.value(db, *key) for key in keys[1:])
            )
            ack, next_rows = self._plan(head, saved, *rows, request)
            if next_rows is not None:
                for (table, key), value in zip(((HEADS, owner), *keys), next_rows, strict=True):
                    db.execute(
                        f"INSERT INTO {table}(owner,value) VALUES (?,?) "
                        "ON CONFLICT(owner) DO UPDATE SET value=excluded.value",
                        (key, canonical_json(value).decode()),
                    )
            return ack

    def _firestore(self, owner, receipt_key, request):
        client = self.store.client
        if client._database != "user-data":
            raise ContractError("authorization_unavailable")
        reference = self.heads._reference(owner)

        @firestore.transactional
        def write(transaction):
            head = self.heads._decode(self.heads._firestore(reference, transaction))
            keys = self._keys(owner, receipt_key, head, request)
            refs = tuple(client.collection(collection).document(key) for collection, key in keys)
            saved, index, fence = read_documents(client, transaction, refs)
            ack, next_rows = self._plan(head, saved, index, fence, request)
            if next_rows is not None:
                current, receipt, next_index, next_fence = next_rows
                transaction.set(reference, {"view": canonical_json(current)})
                transaction.create(refs[0], receipt)
                transaction.set(refs[1], next_index)
                transaction.set(refs[2], next_fence)
            return ack

        return write(BoundedTransaction(client, max_attempts=3))
