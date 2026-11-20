"""Persistent, scope-bound inventory of references to retired registry evidence."""

import argparse
import hashlib
import json
import re
import time

from google.cloud import firestore

from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import verify_jws
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json, strict_json_loads
from folioview_shared.encrypted.private_resources import (
    plan_history_watermark,
    validate_history_reference,
)
from folioview_shared.firestore import BoundedTransaction

from ..resources import (
    FirestoreUserResourceStore,
    ResourceUnavailable,
    SQLiteUserResourceStore,
    get_resource_store,
)
from .authority_cutover import UserAuthorityCutover
from .recovery import ClosedModel, Digest, Identifier, KeyId, Version

COLLECTION = "user_private_registry_retention"
MAX_REFERENCES = 256
MAX_BYTES = 220_000
ARCHIVE_HOLDER = "user_original_archive"
HEX_DIGEST = re.compile(r"[a-f0-9]{64}")


class RetiredRegistryScope(ClosedModel):
    ownerSubject: Digest
    vaultId: Identifier
    rootKeyId: KeyId
    registryEpoch: Version


def _reference_key(reference):
    return hashlib.sha256(
        canonical_json([reference["holderId"], reference["referenceId"]])
    ).hexdigest()


class RegistryRetention:
    """References and the retention floor share a single atomic record."""

    def __init__(self, store):
        self.store = store
        if isinstance(store, SQLiteUserResourceStore):
            with store.connection() as db:
                db.execute(
                    f"CREATE TABLE IF NOT EXISTS {COLLECTION} "
                    "(scope TEXT PRIMARY KEY, body BLOB NOT NULL)"
                )

    @staticmethod
    def _decode(raw, scope):
        initial = {**scope, "generation": 1, "committedThroughSequence": 0}
        if raw is None:
            return {"watermark": initial, "references": {}, "released": {}}
        try:
            value = strict_json_loads(raw, max_bytes=MAX_BYTES)
            if type(value) is not dict or value.keys() != {"watermark", "references", "released"}:
                raise ValueError
            floor = value["watermark"]
            refs = value["references"]
            released = value["released"]
            if (
                type(floor) is not dict
                or any(floor.get(k) != v for k, v in scope.items())
                or type(refs) is not dict
                or type(released) is not dict
                or len(refs) + len(released) > MAX_REFERENCES
                or bool(refs.keys() & released.keys())
                or any(
                    not HEX_DIGEST.fullmatch(key)
                    or type(digest) is not str
                    or not HEX_DIGEST.fullmatch(digest)
                    for key, digest in released.items()
                )
                or any(
                    _reference_key(validate_history_reference(ref, watermark=floor)) != key
                    for key, ref in refs.items()
                )
            ):
                raise ValueError
            plan_history_watermark(
                floor, retired_through=floor["committedThroughSequence"], references=[]
            )
            return value
        except (ContractError, KeyError, TypeError, ValueError):
            raise ContractError("authorization_unavailable") from None

    def _record(self, scope, edit=None):
        values = scope.model_dump()
        key = hashlib.sha256(canonical_json(values)).hexdigest()

        def updated(raw):
            record = self._decode(raw, values)
            if edit is None or not edit(record):
                return record, None
            encoded = canonical_json(record)
            if len(encoded) > MAX_BYTES:
                raise ContractError("payload_too_large")
            return record, encoded

        if isinstance(self.store, SQLiteUserResourceStore):
            try:
                with self.store.connection() as db:
                    db.execute("BEGIN IMMEDIATE" if edit is not None else "BEGIN")
                    row = db.execute(
                        f"SELECT body FROM {COLLECTION} WHERE scope=?", (key,)
                    ).fetchone()
                    record, body = updated(row[0] if row else None)
                    if body is not None:
                        db.execute(
                            f"INSERT INTO {COLLECTION} (scope, body) VALUES (?, ?) "
                            "ON CONFLICT(scope) DO UPDATE SET body=excluded.body",
                            (key, body),
                        )
                return record
            except ResourceUnavailable as error:
                if isinstance(error.__cause__, ContractError):
                    raise error.__cause__ from None
                raise ContractError("authorization_unavailable") from None

        if (
            not isinstance(self.store, FirestoreUserResourceStore)
            or self.store.client._database != "user-data"
        ):
            raise ContractError("authorization_unavailable")
        reference = self.store.client.collection(COLLECTION).document(key)

        def read(transaction=None):
            snapshot = reference.get(transaction=transaction, timeout=4, retry=None)
            raw = None
            if snapshot.exists:
                row = snapshot.to_dict()
                if (
                    type(row) is not dict
                    or row.keys() != {"body"}
                    or type(row["body"]) is not bytes
                ):
                    raise ContractError("authorization_unavailable")
                raw = row["body"]
            record, body = updated(raw)
            if body is not None:
                transaction.set(reference, {"body": body})
            return record

        if edit is None:
            return read()
        return firestore.transactional(read)(BoundedTransaction(self.store.client, max_attempts=3))

    def register(self, scope, reference):
        """Register an exact live reference before its consumer publishes a receipt."""

        def register(record):
            value = validate_history_reference(reference, watermark=record["watermark"])
            refs = record["references"]
            key = _reference_key(value)
            if key in record["released"]:
                raise ContractError("version_conflict")
            if key in refs:
                if refs[key] != value:
                    raise ContractError("version_conflict")
                return False
            if len(refs) + len(record["released"]) >= MAX_REFERENCES:
                raise ContractError("payload_too_large")
            refs[key] = value
            return True

        self._record(scope, register)

    def release(self, scope, reference):
        """Release precisely the reference whose consumer has independently moved off it."""

        def release(record):
            original_floor = {**record["watermark"], "committedThroughSequence": 0}
            value = validate_history_reference(reference, watermark=original_floor)
            if value["holderId"] == ARCHIVE_HOLDER:
                raise ContractError("version_conflict")
            refs = record["references"]
            key = _reference_key(value)
            digest = hashlib.sha256(canonical_json(value)).hexdigest()
            released = record["released"]
            if key in released:
                if released[key] != digest:
                    raise ContractError("version_conflict")
                return False
            if key not in refs:
                raise ContractError("not_found")
            if refs[key] != value:
                raise ContractError("version_conflict")
            del refs[key]
            released[key] = digest
            return True

        self._record(scope, release)

    def audit_original(self, uid, vault, *, now, record_reference=False):
        """Inventory the full range still read by the existing original archive lifecycle."""
        proof = UserAuthorityCutover(self.store).read_start(
            uid, vault, "registry_retention_audit", now=now, allow_deleted=True
        )
        transition = verify_jws(
            proof["signedTransition"],
            proof["rootJwk"],
            typ="fv-control+jws",
            expected_kid=proof["rootKeyId"],
        )
        prior = transition["previousHead"]
        scope = RetiredRegistryScope(
            ownerSubject=proof["ownerSubject"],
            vaultId=proof["vaultId"],
            rootKeyId=proof["rootKeyId"],
            registryEpoch=prior["registryEpoch"],
        )
        hold = {
            **scope.model_dump(),
            "contractVersion": CONTRACT_VERSION,
            "profile": "folioview.private-history-reference.v1",
            "holderId": ARCHIVE_HOLDER,
            "referenceId": "original_chain",
            "purpose": "recovery",
            "firstSequence": 1,
            "lastSequence": prior["registrySequence"],
        }
        if record_reference:
            self.register(scope, hold)
        record = self._record(scope)
        refs = record["references"]
        key = _reference_key(hold)
        if key in record["released"] or (key in refs and refs[key] != hold):
            raise ContractError("version_conflict")
        refs.setdefault(key, hold)
        plan = plan_history_watermark(
            record["watermark"],
            retired_through=prior["registrySequence"],
            references=list(refs.values()),
        )
        return {
            "registryEpoch": scope.registryEpoch,
            "retiredEntries": prior["registrySequence"],
            "protectedEntries": prior["registrySequence"] - plan["committedThroughSequence"],
            "deletableEntries": 0,
            "references": len(refs),
            "coverageComplete": False,
        }


def main():
    parser = argparse.ArgumentParser(description="Audit retained original registry evidence")
    parser.add_argument("uid", help="Exact Owner Firebase UID")
    parser.add_argument("vault", help="Exact vault ID")
    parser.add_argument(
        "--record-reference", action="store_true", help="Persist the existing archive's protection"
    )
    args = parser.parse_args()
    report = RegistryRetention(get_resource_store()).audit_original(
        args.uid, args.vault, now=int(time.time()), record_reference=args.record_reference
    )
    print(json.dumps(report))


if __name__ == "__main__":
    main()
