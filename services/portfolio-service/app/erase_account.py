"""Operator-only erasure of a frozen account's Portfolio database records."""

import argparse
import json
import os
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import firebase_admin
from firebase_admin import auth

from folioview_shared.identity import owner_key

from .erasure import _GENERATION, _PAGE, authority_generation
from .store import (
    ACCOUNT_COLLECTIONS,
    FirestorePortfolioStore,
    SQLitePortfolioStore,
    StoreUnavailable,
)


def account_records(store, uid, *, apply=False):
    owner = owner_key(uid)
    total = 0
    for collection in ACCOUNT_COLLECTIONS:
        after = None
        while True:

            def page(unit, collection=collection, after=after):
                rows = unit.erasure_page(collection, owner=owner, limit=_PAGE, after=after)
                if any(
                    identity != owner or not path.startswith(collection + "/")
                    for path, identity, _ in rows
                ):
                    raise StoreUnavailable
                if apply:
                    for path, _, _ in rows:
                        unit.delete(path)
                return rows

            rows = store.transact(page)
            total += len(rows)
            if len(rows) < _PAGE:
                break
            after = rows[-1][0]
    if not apply:
        return total

    # A fetch that was in flight while pre-existing authorities were being
    # removed must not reinstall one. Disabled identity and drained workers
    # prevent new calls; this counter contains no account-specific data.
    def invalidate(unit):
        unit.put(_GENERATION, {"generation": authority_generation(unit) + 1})

    store.transact(invalidate)
    return account_records(store, uid)


def operator_target(parser, args, *, recovery_inventory=False):
    if args.sqlite:
        if args.database or not args.sqlite.is_file():
            parser.error("Select an existing Portfolio SQLite database")
        with closing(sqlite3.connect(args.sqlite.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            columns = db.execute("PRAGMA table_info(portfolio_documents)").fetchall()
        if [column[1] for column in columns] != ["path", "body"]:
            parser.error("Select an existing Portfolio SQLite database")
        return SQLitePortfolioStore(args.sqlite)
    inventory = recovery_inventory and not args.apply
    restore = inventory and re.fullmatch(
        r"portfolio-restore-[a-z0-9][a-z0-9-]{0,38}", args.database or ""
    )
    if not args.project or (args.database != "portfolio" and not restore):
        parser.error("Specify an explicit project and the named portfolio database")
    emulator = os.getenv("FIRESTORE_EMULATOR_HOST")
    local_read = (
        inventory
        and args.project.startswith("demo-")
        and re.fullmatch(r"(localhost|127\.0\.0\.1):[0-9]{1,5}", emulator or "")
    )
    if os.getenv("FIREBASE_AUTH_EMULATOR_HOST") or (emulator and not local_read):
        parser.error("Use the isolated adapter tests for emulators")
    return FirestorePortfolioStore(args.project, args.database)


def operator_arguments(description):
    parser = argparse.ArgumentParser(description=description)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--project")
    target.add_argument("--sqlite", type=Path)
    parser.add_argument("--database")
    parser.add_argument(
        "--apply", action="store_true", help="Permanently erase the selected records"
    )
    return parser


def require_disabled(project, uid):
    app = firebase_admin.initialize_app(options={"projectId": project}, name="portfolio-erasure")
    try:
        if not auth.get_user(uid, app=app).disabled:
            raise ValueError("Disable the verified account and drain in-flight writes first")
    finally:
        firebase_admin.delete_app(app)


def main(argv=None):
    parser = operator_arguments(__doc__)
    args = parser.parse_args(argv)
    uid = sys.stdin.readline(1024).removesuffix("\n")
    if not uid or len(uid) > 128 or any(ord(c) < 32 for c in uid) or sys.stdin.read(1):
        parser.error("Supply exactly one verified Firebase UID on standard input")
    try:
        store = operator_target(parser, args, recovery_inventory=True)
        if args.apply and args.project:
            require_disabled(args.project, uid)
        remaining = account_records(store, uid, apply=args.apply)
    except Exception:
        parser.exit(1, "Portfolio erasure incomplete. Verify the target, identity and access.\n")
    print(json.dumps({"scope": "portfolio.account", "remaining": remaining}))
    return int(args.apply and remaining > 0)


if __name__ == "__main__":
    raise SystemExit(main())
