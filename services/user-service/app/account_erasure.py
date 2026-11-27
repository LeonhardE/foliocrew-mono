"""Offline User-service inventory and physical removal for one verified Firebase account."""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import firebase_admin
from firebase_admin import auth
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from folioview_shared.encrypted.crypto import verify_jws
from folioview_shared.encrypted.jsonutil import canonical_json, strict_json_loads
from folioview_shared.identity import owner_key

from .invitation_erasure import (
    ErasureIncomplete,
    InvitationReviewRequired,
    invitation_matches,
    joined_binding,
)
from .private_resources.archive_lifecycle import PrivateArchiveLifecycle
from .private_resources.authority_cutover import ARCHIVE_RECORDS, HANDOVERS, WITNESSES
from .private_resources.display_name_cleanup import NAMES, OPERATIONS, erase_retired_names
from .private_resources.key_renewals import RECEIPTS
from .private_resources.legacy_baselines import COLLECTION as BASELINES
from .private_resources.legacy_baselines import LegacyVaultBaselines
from .private_resources.recovery import COLLECTION as HEADS
from .private_resources.registry_pages import COLLECTION as HISTORY
from .private_resources.registry_pages import _index
from .private_resources.registry_retention import COLLECTION as RETENTION
from .private_resources.registry_retention import RetiredRegistryScope
from .private_resources.registry_updates import REGISTRY_MUTATIONS
from .private_resources.report_sources import HOLDINGS_FENCES, HoldingsFence, holdings_fence_key
from .private_resources.source_invalidations import INVALIDATION_RECEIPTS, SOURCE_INDEX
from .private_resources.source_registrations import SOURCE_REGISTRATIONS
from .resource_versions import KINDS, version_key
from .resources import COLLECTIONS, FirestoreUserResourceStore
from .watchlist import fx_owner
from .workspace_invitations import INVITATIONS, MEMBERS, invitation_id


@dataclass(frozen=True)
class Subject:
    uid: str
    email: str
    google_subject: str


def verified_subject(record, expected_email: str, *, apply: bool) -> Subject:
    google = [provider for provider in record.provider_data if provider.provider_id == "google.com"]
    if (
        not record.uid
        or not record.email_verified
        or not record.email
        or record.email.lower() != expected_email
        or len(google) != 1
        or not google[0].uid
        or (google[0].email or "").lower() != expected_email
        or (apply and not record.disabled)
    ):
        raise ErasureIncomplete("Identity verification or account suspension is incomplete.")
    return Subject(record.uid, expected_email, google[0].uid)


def fixed_keys(subject):
    uid = subject.uid
    owner = owner_key(uid)
    refs = [
        (table, owner)
        for table in (
            *COLLECTIONS.values(),
            HEADS,
            WITNESSES,
            HANDOVERS,
            ARCHIVE_RECORDS,
            SOURCE_INDEX,
            MEMBERS,
        )
    ]
    refs.append((COLLECTIONS["watchlist"], fx_owner(uid)))
    for kind in KINDS:
        refs.extend(
            (table, version_key(uid, kind))
            for table in ("user_resource_versions", "user_resource_initializations")
        )
    return refs


# The only non-fixed User document IDs are scoped receipts, names and older packed records.
INDEXED = {
    HOLDINGS_FENCES: "ownerSubject",
    SOURCE_REGISTRATIONS: "ownerSubject",
    INVALIDATION_RECEIPTS: "ownerSubject",
    RECEIPTS: "ownerSubject",
    REGISTRY_MUTATIONS: "ownerSubject",
    NAMES: "state.ownerSubject",
    OPERATIONS: "state.ownerSubject",
}
PACKED = {BASELINES: ("key", "body"), HISTORY: ("entry", "entry"), RETENTION: ("scope", "body")}


def packed_owner(table, key, raw):
    # Legacy packed documents have no indexed owner. Verify the storage key reconstructed from
    # the exact format that wrote them; do not match arbitrary occurrences in a signed payload.
    row = strict_json_loads(raw, max_bytes=1_048_576)
    if table == BASELINES:
        owner = row["ownerSubject"]
        digest = hashlib.sha256(raw).hexdigest()
        expected = LegacyVaultBaselines._key(owner, row["vaultId"], digest)
    elif table == RETENTION:
        scope = RetiredRegistryScope.model_validate(
            {name: row["watermark"][name] for name in RetiredRegistryScope.model_fields}
        )
        owner = scope.ownerSubject
        expected = hashlib.sha256(canonical_json(scope.model_dump())).hexdigest()
    else:
        checkpoint = verify_jws(row["bundle"]["checkpoint"], row["rootJwk"], typ="fv-control+jws")
        owner = checkpoint["ownerSubject"]
        expected = _index(
            owner,
            checkpoint["vaultId"],
            row["head"]["registryEpoch"],
            checkpoint["registrySequence"],
        )
    if key != expected:
        raise ErasureIncomplete("A packed record has inconsistent ownership.")
    return owner


def verify_fixed(table, data, subject):
    if table == MEMBERS and data.get("googleSubject") != subject.google_subject:
        raise ErasureIncomplete("Workspace membership is bound to another identity.")


def delivery_refs(client, subject):
    refs = []
    for invite in firestore_invitations(client, subject):
        delivered = invite.reference.get(field_paths=["providerMessageId"], timeout=30)
        if not delivered.exists or delivered.update_time != invite.update_time:
            raise InvitationReviewRequired
        value = delivered.to_dict().get("providerMessageId")
        if value is None:
            continue
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value):
            raise ErasureIncomplete("The delivery reference requires private operator review.")
        refs.append(value)
    return sorted(set(refs))


def sqlite_rows(db, subject):
    present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, key in fixed_keys(subject):
        if table not in present:
            continue
        row = db.execute(f"SELECT value FROM {table} WHERE owner=?", (key,)).fetchone()
        if row is not None:
            if table in (MEMBERS, INVITATIONS):
                verify_fixed(table, strict_json_loads(row[0]), subject)
            yield table, "owner", key
    owner = owner_key(subject.uid)
    if INVITATIONS in present:
        for key, raw in db.execute(f"SELECT owner,value FROM {INVITATIONS}"):
            if invitation_matches(key, strict_json_loads(raw, max_bytes=1_048_576), subject):
                yield INVITATIONS, "owner", key
    for table, field in INDEXED.items():
        if table in present:
            for (key,) in db.execute(
                f"SELECT owner FROM {table} WHERE json_extract(value, ?) = ?", ("$." + field, owner)
            ):
                yield table, "owner", key
    for table, (key_column, field) in PACKED.items():
        if table not in present:
            continue
        db_field = "value" if table == HISTORY else field
        for key, raw in db.execute(f"SELECT {key_column},{db_field} FROM {table}"):
            if isinstance(raw, str):
                raw = raw.encode("utf-8")
            if packed_owner(table, key, raw) == owner:
                yield table, key_column, key


def sqlite_erasure(path, subject, *, apply=False):
    # SQLite exists only for local service databases and isolated restore exercises.
    uri = Path(path).resolve().as_uri() + ("?mode=rw" if apply else "?mode=ro")
    with closing(sqlite3.connect(uri, uri=True)) as db, db:
        db.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        rows = list(sqlite_rows(db, subject))
        if apply:
            for table, column, key in rows:
                db.execute(f"DELETE FROM {table} WHERE {column}=?", (key,))
            if next(sqlite_rows(db, subject), None) is not None:
                raise ErasureIncomplete("SQLite verification found retained User data.")
        return dict(sorted(Counter(table for table, _, _ in rows).items()))


def pages(query):
    cursor = None
    while True:
        page = query.order_by("__name__").limit(64)
        if cursor is not None:
            page = page.start_after(cursor)
        rows = list(page.stream(timeout=60))
        yield from rows
        if len(rows) < 64:
            return
        cursor = rows[-1]


def firestore_invitations(client, subject):
    # Before owner bindings existed an old address may be the only lookup key.
    invitations = client.collection(INVITATIONS)
    fields = ["email", "status", "joinedOwner", "joinedGoogleSubject"]
    current = invitation_id(subject.email) if subject.email.isascii() else None
    if current:
        row = invitations.document(current).get(field_paths=fields, timeout=30)
        if row.exists and invitation_matches(row.id, row.to_dict(), subject):
            yield row
    owner = owner_key(subject.uid)
    joined = invitations.where(filter=FieldFilter("status", "==", "joined"))
    for row in pages(joined.select(["joinedOwner", "joinedGoogleSubject"])):
        if row.id == current:
            continue
        bound_owner, google = joined_binding(row.to_dict())
        if bound_owner != owner:
            continue
        if google != subject.google_subject:
            raise InvitationReviewRequired
        matched = row.reference.get(field_paths=fields, timeout=30)
        if (
            not matched.exists
            or matched.update_time != row.update_time
            or not invitation_matches(matched.id, matched.to_dict(), subject)
        ):
            raise InvitationReviewRequired
        yield matched


def firestore_rows(client, subject):
    yield from firestore_invitations(client, subject)
    owner = owner_key(subject.uid)
    refs = [client.collection(table).document(key) for table, key in fixed_keys(subject)]
    for row in client.get_all(refs, field_paths=["email", "googleSubject"], timeout=30):
        if row.exists:
            verify_fixed(row.reference.parent.id, row.to_dict(), subject)
            yield row
    for table, field in INDEXED.items():
        query = client.collection(table).where(filter=FieldFilter(field, "==", owner))
        yield from pages(query.select([field]))
    for table, (_, field) in PACKED.items():
        for row in pages(client.collection(table).select([field])):
            if packed_owner(table, row.id, row.get(field)) == owner:
                yield row


def firestore_erasure(client, subject, *, apply, check_suspension):
    # Keep only refs and versions, never a payload. Finish the complete inventory before
    # the first write. Version preconditions prevent deleting a record re-bound after inventory.
    inventory = [(row.reference, row.update_time) for row in firestore_rows(client, subject)]
    counts = Counter(ref.parent.id for ref, _ in inventory)
    if apply:
        for start in range(0, len(inventory), 100):
            check_suspension()
            batch = client.batch()
            for ref, version in inventory[start : start + 100]:
                batch.delete(ref, option=client.write_option(last_update_time=version))
            batch.commit(timeout=30)
        check_suspension()
        if next(firestore_rows(client, subject), None) is not None:
            raise ErasureIncomplete("Additional or recreated User records require reconciliation.")
    return dict(sorted(counts.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--restore-inventory", action="store_true")
    parser.add_argument("--delivery-refs", action="store_true")
    parser.add_argument("--retired-archive-only", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--retired-names-only",
        action="store_true",
        help="Repair alias history of already deleted holdings on an active account.",
    )
    args = parser.parse_args()
    if args.retired_archive_only and (
        args.restore_inventory or args.retired_names_only or args.delivery_refs
    ):
        parser.error("--retired-archive-only must be run separately.")
    if args.delivery_refs and (args.restore_inventory or args.apply or args.retired_names_only):
        parser.error("--delivery-refs is a separate read-only operation.")
    if args.restore_inventory and (args.apply or args.retired_names_only):
        parser.error("--restore-inventory is strictly read-only.")
    if args.database not in {"user-data", "(default)"} and not (
        args.restore_inventory and re.fullmatch("[a-z][a-z0-9-]{2,61}[a-z0-9]", args.database)
    ):
        parser.error("Unknown User database.")
    emulator = os.getenv("FIRESTORE_EMULATOR_HOST")
    if os.getenv("FIREBASE_AUTH_EMULATOR_HOST") or (
        emulator
        and not (
            args.restore_inventory
            and re.fullmatch(r"demo-[a-z0-9-]+", args.project)
            and re.fullmatch(r"(?:127\.0\.0\.1|localhost|\[::1\]):[0-9]{1,5}", emulator)
        )
    ):
        parser.error("Emulator use requires a read-only demo-project restore on loopback.")
    request = strict_json_loads(sys.stdin.buffer.read(2049), max_bytes=2048)
    if (
        not isinstance(request, dict)
        or set(request)
        != ({"uid", "email", "googleSubject"} if args.restore_inventory else {"uid", "email"})
        or any(not isinstance(v, str) or not v.strip() for v in request.values())
    ):
        parser.error("Provide the verified uid and email as a JSON object on standard input.")
    if args.restore_inventory:
        client = firestore.Client(project=args.project, database=args.database)
        subject = Subject(request["uid"], request["email"], request["googleSubject"])
        counts = Counter(row.reference.parent.id for row in firestore_rows(client, subject))
        print(
            json.dumps(
                {
                    "database": args.database,
                    "mode": "restore-inventory",
                    "matched": dict(sorted(counts.items())),
                }
            )
        )
        return
    app = firebase_admin.initialize_app(options={"projectId": args.project, "httpTimeout": 10})

    def identity():
        record = auth.get_user(request["uid"], app=app)
        if record.uid != request["uid"]:
            raise ErasureIncomplete("Identity lookup mismatch.")
        return verified_subject(
            record,
            request["email"],
            apply=args.apply and not (args.retired_names_only or args.retired_archive_only),
        )

    subject = identity()
    if args.delivery_refs:
        client = firestore.Client(project=args.project, database=args.database)
        print(
            json.dumps(
                {
                    "database": args.database,
                    "providerMessageIds": delivery_refs(client, subject),
                    "providerSearchRequired": True,
                }
            )
        )
        return

    def check_suspension():
        if identity() != subject:
            raise ErasureIncomplete("The verified identity has changed.")

    if args.retired_archive_only:
        if args.database != "user-data":
            parser.error("Migrated archive authority belongs to user-data.")
        owner = owner_key(subject.uid)
        service = PrivateArchiveLifecycle(FirestoreUserResourceStore(args.project, args.database))
        head = service.cutover._read(((HEADS, owner),))[0]
        changed = 0
        if head and head.get("handover"):
            head, receipt = service.retirement(subject.uid, head["vaultId"], int(time.time()))
            if receipt:
                check_suspension()
                changed = service.cutover.verifier.baselines.erase_archives(
                    owner, head["vaultId"], head["rootKeyId"], apply=args.apply
                )
        print(json.dumps({"mode": "retired-archive", "apply": args.apply, "matched": changed}))
        return
    if args.retired_names_only:
        if args.database != "user-data":
            parser.error("The private holdings authority belongs to user-data.")
        store = FirestoreUserResourceStore(args.project, args.database)
        owner = owner_key(subject.uid)
        query = store.client.collection(HOLDINGS_FENCES).where(
            filter=FieldFilter("ownerSubject", "==", owner)
        )
        changed = 0
        for row in pages(query):
            fence = HoldingsFence.model_validate(row.to_dict())
            ref = fence.binding.ref.model_dump()
            if fence.ownerSubject != owner or row.id != holdings_fence_key(
                owner, fence.vaultId, ref["resourceId"]
            ):
                raise ErasureIncomplete("The holdings fence has inconsistent ownership.")
            if fence.state == "deleted":
                changed += erase_retired_names(store, owner, ref, apply=args.apply)
        print(json.dumps({"mode": "retired-source-names", "apply": args.apply, "matched": changed}))
        return
    client = firestore.Client(project=args.project, database=args.database)
    counts = firestore_erasure(client, subject, apply=args.apply, check_suspension=check_suspension)
    print(
        json.dumps(
            {
                "database": args.database,
                "mode": "apply" if args.apply else "inventory",
                "matched": counts,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except InvitationReviewRequired:
        sys.exit(
            "Invitation ownership requires review. Verify the original admission before erasing."
        )
    except Exception:
        # SDK errors can include private document paths or the account's email.
        sys.exit("User erasure incomplete. Verify the identity, database access and case status.")
