"""Current report decisions from User's private authority and local list versions."""

import hashlib
import time
from typing import Literal

from google.cloud import firestore

from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json
from folioview_shared.encrypted.private_resources import (
    decide_report_sources,
    report_source_request,
)
from folioview_shared.firestore import BoundedTransaction
from folioview_shared.identity import owner_key

from ..firestore_reads import read_documents
from ..resources import FirestoreUserResourceStore, SQLiteUserResourceStore, read_pair
from .recovery import (
    COLLECTION as RECOVERY_HEADS,
)
from .recovery import ClosedModel, EpochSeconds, Identifier, RecoveryHeads, Version

HOLDINGS_FENCES = "user_private_holdings_fences"
MAX_DECISION_DOCUMENTS = 13


class HoldingsRef(ClosedModel):
    kind: Literal["holdings"]
    sourceService: Literal["portfolio"]
    resourceId: Identifier
    incarnation: Identifier


class HoldingsBinding(ClosedModel):
    ref: HoldingsRef
    sourceEpoch: Version


class HoldingsFence(ClosedModel):
    ownerSubject: Identifier
    vaultId: Identifier
    binding: HoldingsBinding
    state: Literal["eligible", "revoking", "disconnected", "deleted"]
    currentRevision: EpochSeconds


def holdings_fence_key(owner, vault, resource_id):
    return hashlib.sha256(canonical_json([owner, vault, resource_id])).hexdigest()


def missing(binding):
    return {
        "binding": {"ref": binding["ref"], "sourceEpoch": binding["sourceEpoch"]},
        "state": "missing",
        "currentRevision": 0,
    }


def list_state(binding, item):
    if item is None or item["ref"]["resourceId"] != binding["ref"]["resourceId"]:
        return missing(binding)
    return {
        "binding": {"ref": item["ref"], "sourceEpoch": item["sourceEpoch"]},
        "state": "eligible",
        "currentRevision": item["revision"],
    }


def holdings_state(binding, row, owner, vault):
    if row is None:
        return missing(binding)
    fence = HoldingsFence.model_validate(row).model_dump()
    if (
        fence.pop("ownerSubject") != owner
        or fence.pop("vaultId") != vault
        or fence["binding"]["ref"]["resourceId"] != binding["ref"]["resourceId"]
    ):
        raise ContractError("source_unavailable")
    return fence


class ReportSourceAuthority:
    def __init__(self, store):
        self.store = store
        if isinstance(store, SQLiteUserResourceStore):
            self.recovery = RecoveryHeads(store)
            with store.connection() as db:
                db.execute(
                    f"CREATE TABLE IF NOT EXISTS {HOLDINGS_FENCES} "
                    "(owner TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )

    def decide(self, uid, request):
        request = report_source_request(request)
        owner, vault = owner_key(uid), request["vaultId"]
        if owner != request["ownerSubject"]:
            raise ContractError("insufficient_scope")
        try:
            head, lists, fences = self._read(uid, owner, vault, request["resources"])
            if head is None:
                raise ContractError("source_unavailable")
            if head["ownerSubject"] != owner:
                raise ContractError("source_unavailable")
            if head["vaultId"] != vault:
                raise ContractError("insufficient_scope")
            if head.get("handover") is None:
                raise ContractError("source_unavailable")
            states = []
            for binding in request["resources"]:
                ref = binding["ref"]
                if ref["sourceService"] == "portfolio":
                    states.append(holdings_state(binding, fences[ref["resourceId"]], owner, vault))
                else:
                    states.append(list_state(binding, lists[ref["kind"]]))
        except ContractError:
            raise
        except Exception:
            raise ContractError("source_unavailable") from None
        return decide_report_sources(
            request,
            snapshot={"ownerSubject": owner, "vaultId": vault, "resources": states},
            now=int(time.time()),
        )

    def _read(self, uid, owner, vault, bindings):
        kinds = tuple(
            dict.fromkeys(
                item["ref"]["kind"] for item in bindings if item["ref"]["sourceService"] == "user"
            )
        )
        keys = {
            item["ref"]["resourceId"]: holdings_fence_key(owner, vault, item["ref"]["resourceId"])
            for item in bindings
            if item["ref"]["sourceService"] == "portfolio"
        }
        if isinstance(self.store, SQLiteUserResourceStore):
            with self.store.connection() as db:
                db.execute("BEGIN")
                head = self.recovery._decode(self.recovery._local(db, owner))
                lists = {
                    kind: read_pair(kind, *self.store.pair(db, uid, kind))[1] for kind in kinds
                }
                fences = {
                    resource_id: self.store.value(db, HOLDINGS_FENCES, key)
                    for resource_id, key in keys.items()
                }
            return head, lists, fences
        if not isinstance(self.store, FirestoreUserResourceStore):
            raise ContractError("source_unavailable")
        client = self.store.client
        references = [
            client.collection(RECOVERY_HEADS).document(owner),
            *(ref for kind in kinds for ref in self.store.references(uid, kind)),
            *(client.collection(HOLDINGS_FENCES).document(key) for key in keys.values()),
        ]

        @firestore.transactional
        def read(transaction):
            first, *rows = read_documents(
                client, transaction, references, maximum=MAX_DECISION_DOCUMENTS
            )
            if first is not None and (first.keys() != {"view"} or type(first["view"]) is not bytes):
                raise ContractError("source_unavailable")
            head = RecoveryHeads._decode(first["view"] if first else None)
            lists = {
                kind: read_pair(kind, rows[2 * i], rows[2 * i + 1])[1]
                for i, kind in enumerate(kinds)
            }
            fences = dict(zip(keys, rows[2 * len(kinds) :], strict=True))
            return head, lists, fences

        return read(BoundedTransaction(client, max_attempts=2))
