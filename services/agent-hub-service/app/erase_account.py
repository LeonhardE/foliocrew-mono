"""Verified single-subject erasure of the dedicated Agent Hub database."""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field

from google.cloud import firestore

from .account_legacy_paths import FIELDS, recover_paths
from .account_writes import HOLDS, OWNERSHIP, POOLS, direct_owner, hold_path, index_path, valid_uid
from .store import COLLECTIONS, document_path

# Cloud Run requests have a maximum 60-minute lifetime. Include the longest
# Firestore transaction lifetime and clock margin before removing the per-owner lock.
DRAIN_SECONDS = 65 * 60
GLOBAL_HOLD = hold_path("active-count")
PROJECTION = FIELDS + [
    "ownerSubject",
    "ownerUid",
    "scope",
    "context.ownerSubject",
    "definition.ownerSubject",
    "identity.ownerSubject",
    "state.ownerSubject",
    "request.ownerSubject",
    "record.ownerSubject",
    "metadata.ownerSubject",
    "target",
    "vaultId",
    "entries",
]


@dataclass
class Inventory:
    owned: list = field(default_factory=list)
    indexes: list = field(default_factory=list)
    pools: list = field(default_factory=list)
    unclassified: int = 0
    legacy: list = field(default_factory=list)
    held_until: int | None = None

    def report(self):
        return {
            "scope": "agent-hub.account",
            "remaining": len(self.owned)
            + len(self.indexes)
            + len(self.pools)
            + self.unclassified
            + int(self.held_until is not None),
            "unclassified": self.unclassified,
            "writeHoldUntil": self.held_until,
        }


def _primary_paths(owner, vaults):
    paths = {
        str(document_path(c, owner))
        for c in (
            "hub_vaults",
            "hub_executor_owners",
            "hub_oauth_owners",
            "hub_result_indexes",
            "hub_private_resource_writer_fences",
        )
    }
    for vault in vaults:
        paths.update(
            str(document_path(c, owner, vault))
            for c in (
                "hub_task_indexes",
                "hub_center_lifecycle",
                "hub_upload_cancellations",
                "hub_persistent_result_indexes",
                "hub_inbox_cursors",
                "hub_vault_lifecycle",
            )
        )
    return paths


def inventory(client, owner):
    plan = Inventory()
    rows, claims, owners = {}, {}, {owner: set()}
    for coll in client.collections():
        if coll.id not in COLLECTIONS:
            plan.unclassified += 1
            continue
        # list_documents includes missing parents with live descendants. Hub's
        # supported schema is flat; a nested collection needs separate attribution.
        for ref in coll.list_documents():
            if next(ref.collections(), None) is not None:
                plan.unclassified += 1
            snap = ref.get(field_paths=None if coll.id == HOLDS else PROJECTION)
            if not snap.exists:
                continue
            row = snap.to_dict()
            path = ref.path
            if coll.id == HOLDS:
                if path == hold_path(owner):
                    plan.held_until = row["releaseAfter"]
                continue
            if coll.id in POOLS:
                if path != document_path(coll.id, "pool") or not isinstance(
                    row.get("entries"), dict
                ):
                    plan.unclassified += 1
                    continue
                # Entries with no account association are unauthenticated flow nonces.
                if any(
                    v.get("ownerSubject") is not None and direct_owner(v) is None
                    for v in row["entries"].values()
                ):
                    plan.unclassified += 1
                if any(direct_owner(v) == owner for v in row["entries"].values()):
                    plan.pools.append(ref)
                continue
            subject = direct_owner(row)
            if subject is not None:
                owners.setdefault(subject, set())
                if isinstance(row.get("vaultId"), str):
                    owners[subject].add(row["vaultId"])
            if coll.id == OWNERSHIP:
                target = row.get("target")
                if (
                    subject is None
                    or not isinstance(target, str)
                    or len(target.split("/")) != 2
                    or target.split("/")[0] not in COLLECTIONS - {HOLDS, OWNERSHIP}
                    or index_path(target) != path
                ):
                    plan.unclassified += 1
                    continue
                claims[target] = subject
                if subject == owner:
                    plan.indexes.append(snap)
            else:
                rows[path] = (subject, snap)
    keys = {
        path: subject
        for subject, vaults in owners.items()
        for path in _primary_paths(subject, vaults)
    }
    keys = recover_paths(rows, claims, keys)
    for path, (subject, snap) in rows.items():
        evidence = {v for v in (claims.get(path), subject, keys.get(path)) if v is not None}
        if len(evidence) != 1:
            plan.unclassified += 1
        elif owner in evidence:
            plan.owned.append(snap)
            if subject is None and path not in claims:
                plan.legacy.append(snap)
    return plan


def _hold(client, owner, now, *, release=False):
    ref = client.document(hold_path(owner))
    global_ref = client.document(GLOBAL_HOLD)

    @firestore.transactional
    def change(tx):
        current, total = ref.get(transaction=tx), global_ref.get(transaction=tx)
        count = total.get("count") if total.exists else 0
        if current.exists and count < 1:
            raise ValueError("Inconsistent writer hold.")
        if release:
            if current.exists:
                tx.delete(ref)
                if count == 1:
                    tx.delete(global_ref)
                else:
                    tx.set(global_ref, {"count": count - 1})
        elif not current.exists:
            tx.set(ref, {"releaseAfter": int(now) + DRAIN_SECONDS})
            tx.set(global_ref, {"count": count + 1})

    change(client.transaction())


def hold_writes(client, uid, *, clock=time.time):
    owner = valid_uid(uid)
    _hold(client, owner, clock())
    observed = client.document(hold_path(owner)).get()
    if not observed.exists or type(observed.get("releaseAfter")) is not int:
        raise ValueError("Write hold was not acknowledged.")
    return {"scope": "agent-hub.account", "writeHold": True}


def _scrub_pool(client, ref, owner):
    @firestore.transactional
    def update(tx):
        saved = ref.get(transaction=tx)
        if not saved.exists:
            return
        row = saved.to_dict()
        entries = {k: v for k, v in row["entries"].items() if direct_owner(v) != owner}
        if len(entries) != len(row["entries"]):
            if entries:
                tx.update(ref, {"entries": entries})
            else:
                tx.delete(ref)

    update(client.transaction())


def _index_legacy(client, owner, records):
    """Keep proven legacy scope across a crash after a parent disappears."""

    @firestore.transactional
    def record(tx, group):
        targets = [s.reference for s in group]
        snapshots = {
            s.reference.path: s
            for s in client.get_all(targets, field_paths=["ownerSubject"], transaction=tx)
        }
        for original in group:
            path = original.reference.path
            saved = snapshots.get(path)
            if not saved or not saved.exists or saved.update_time != original.update_time:
                raise ValueError("Ownership evidence changed. Retry the inventory.")
        for original in group:
            path = original.reference.path
            tx.set(client.document(index_path(path)), {"ownerSubject": owner, "target": path})

    for start in range(0, len(records), 64):
        record(client.transaction(), records[start : start + 64])


def inspect_or_erase(client, uid, *, apply=False, isolated_restore=False, clock=time.time):
    owner = valid_uid(uid)
    if not apply:
        return inventory(client, owner).report()
    _hold(client, owner, clock())
    plan = inventory(client, owner)
    if plan.unclassified:
        return plan.report()
    if plan.legacy:
        _index_legacy(client, owner, plan.legacy)
        plan = inventory(client, owner)
        if plan.unclassified or plan.legacy:
            return plan.report()
    for ref in plan.pools:
        _scrub_pool(client, ref, owner)
    # Delete ownership indexes last to retain scope proof across interrupted pages.
    for snapshots in (plan.owned, plan.indexes):
        for start in range(0, len(snapshots), 128):
            batch = client.batch()
            for snap in snapshots[start : start + 128]:
                batch.delete(
                    snap.reference, option=client.write_option(last_update_time=snap.update_time)
                )
            batch.commit()
    current = inventory(client, owner)
    if current.report()["remaining"] == 1 and current.held_until is not None:
        if isolated_restore or clock() >= current.held_until:
            _hold(client, owner, clock(), release=True)
            current = inventory(client, owner)
    return current.report()


def require_disabled(project, uid):
    import firebase_admin
    from firebase_admin import auth

    app = firebase_admin.initialize_app(options={"projectId": project}, name="hub-erasure")
    try:
        if not auth.get_user(uid, app=app).disabled:
            raise ValueError("Identity must be disabled.")
    finally:
        firebase_admin.delete_app(app)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--database", required=True)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true")
    action.add_argument("--hold-writes", action="store_true")
    args = parser.parse_args()
    try:
        if args.database != "agent-hub":
            raise ValueError("Unexpected database.")
        uid = sys.stdin.read(512).removesuffix("\n")
        valid_uid(uid)
        if os.getenv("FIRESTORE_EMULATOR_HOST") and not args.project.startswith("demo-"):
            raise ValueError("Use a synthetic emulator project.")
        if args.apply or args.hold_writes:
            require_disabled(args.project, uid)
        client = firestore.Client(project=args.project, database=args.database)
        report = (
            hold_writes(client, uid)
            if args.hold_writes
            else inspect_or_erase(client, uid, apply=args.apply)
        )
    except Exception:
        report = {"scope": "agent-hub.account", "remaining": 1, "error": "verification_failed"}
    print(json.dumps(report, sort_keys=True))
    return int(
        bool(
            report.get("error")
            or report.get("unclassified")
            or (args.apply and report["remaining"])
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
