"""Operator command for removing the three preference documents of one verified account."""

import argparse
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import firebase_admin
from firebase_admin import auth
from google.cloud import firestore

from .preferences import preference_keys


def sqlite_preferences(path: Path, uid: str, *, apply: bool) -> int:
    # mode=rw refuses a mistyped path instead of verifying an empty new database.
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True)) as db, db:
        if apply:
            db.execute("PRAGMA secure_delete=ON")
            db.execute("BEGIN IMMEDIATE")
        keys = preference_keys(uid)
        if apply:
            db.execute("DELETE FROM user_preferences WHERE owner IN (?, ?, ?)", keys)
        return db.execute(
            "SELECT COUNT(*) FROM user_preferences WHERE owner IN (?, ?, ?)", keys
        ).fetchone()[0]


def firestore_preferences(client, uid: str, *, apply: bool) -> int:
    collection = client.collection("user_preferences")
    refs = [collection.document(key) for key in preference_keys(uid)]
    if apply:
        batch = client.batch()
        for ref in refs:
            batch.delete(ref)
        batch.commit(retry=None, timeout=10)

    # Require explicit exists/missing results for all three locations. A partial
    # stream or a lost acknowledgement is an unknown outcome and can be retried.
    expected = {ref.path for ref in refs}
    found = {}
    for row in client.get_all(refs, field_paths=[], retry=None, timeout=10):
        path = row.reference.path
        if path not in expected or path in found:
            raise RuntimeError("Unexpected preference readback")
        found[path] = row.exists
    if found.keys() != expected:
        raise RuntimeError("Incomplete preference readback")
    return sum(found.values())


def require_disabled_account(project: str, uid: str) -> None:
    if os.getenv("FIREBASE_AUTH_EMULATOR_HOST") or os.getenv("FIRESTORE_EMULATOR_HOST"):
        raise RuntimeError("Use isolated local testing for emulated targets")
    app = firebase_admin.initialize_app(options={"projectId": project}, name="config-erasure")
    try:
        if not auth.get_user(uid, app=app).disabled:
            raise ValueError("Disable the verified account and drain its in-flight writes first")
    finally:
        firebase_admin.delete_app(app)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    location = parser.add_mutually_exclusive_group(required=True)
    location.add_argument("--project", help="Firebase and Firestore project")
    location.add_argument("--sqlite", type=Path, help="Existing offline Config database")
    parser.add_argument("--database", help="Explicit Firestore database, including (default)")
    parser.add_argument("--apply", action="store_true", help="Permanently erase the selected rows")
    args = parser.parse_args(argv)
    if bool(args.project) != bool(args.database):
        parser.error("Specify --database together with --project")
    uid = sys.stdin.readline(1024).removesuffix("\n")
    if not uid or len(uid) > 128 or any(ord(ch) < 32 for ch in uid) or sys.stdin.read(1):
        parser.error("Supply exactly one verified Firebase UID on standard input")
    try:
        if args.sqlite:
            remaining = sqlite_preferences(args.sqlite, uid, apply=args.apply)
        else:
            if args.apply:
                require_disabled_account(args.project, uid)
            client = firestore.Client(project=args.project, database=args.database)
            try:
                remaining = firestore_preferences(client, uid, apply=args.apply)
            finally:
                client.close()
    except Exception:
        parser.exit(1, "Preference operation incomplete. Check target, identity and access.\n")
    print(json.dumps({"scope": "config.preferences", "remaining": remaining}))
    return 1 if args.apply and remaining else 0


if __name__ == "__main__":
    raise SystemExit(main())
