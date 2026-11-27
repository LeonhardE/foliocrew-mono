"""Reapply a verified case using the service's own adapter in a quarantined restore."""

import json
import os
import re
import sys


def database_name(database, batch):
    if database not in {"(default)", "agent-hub", "portfolio", "user-data"}:
        raise ValueError("Unsupported database")
    if batch is None:
        return database
    if not re.fullmatch(r"[a-z0-9]{6,24}", batch):
        raise ValueError("Invalid isolated restore batch")
    label = "default" if database == "(default)" else database
    return f"erasure-restore-{batch}-{label}"


def backup_time(source, target, database, batch):
    from google.cloud import firestore_admin_v1

    physical = database_name(database, batch)
    with firestore_admin_v1.FirestoreAdminClient() as admin:
        saved = admin.get_database(name=f"projects/{target}/databases/{physical}", timeout=15)
        path = saved.source_info.backup.backup
        if not path or not path.startswith(f"projects/{source}/locations/"):
            raise ValueError("Unverified backup lineage")
        backup = admin.get_backup(name=path, timeout=15)
        if backup.database != f"projects/{source}/databases/{database}":
            raise ValueError("Backup belongs to another database")
        return backup.snapshot_time.timestamp()


def require_quarantine(source, target, database=None, batch=None):
    if (source == target) != (batch is not None) or not all(
        re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", p) for p in (source, target)
    ):
        raise ValueError("Restore must use a distinct, explicitly selected project")
    if batch is not None:
        database_name(database, batch)
    emulator = os.getenv("FIRESTORE_EMULATOR_HOST")
    if emulator:
        if not target.startswith("demo-") or not re.fullmatch(
            r"(127\.0\.0\.1|localhost):[0-9]{1,5}", emulator
        ):
            raise ValueError("Expected a local disposable restore")
        return
    if batch is not None:
        backup_time(source, target, database, batch)
        return
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    with AuthorizedSession(credentials) as session:
        response = session.get(
            f"https://cloudresourcemanager.googleapis.com/v3/projects/{target}", timeout=10
        )
        response.raise_for_status()
        metadata = response.json()
    if (
        metadata.get("projectId") != target
        or metadata.get("state") != "ACTIVE"
        or metadata.get("labels", {}).get("foliocrew-restore-of") != source
    ):
        raise ValueError("The restore project has not been designated for this source")


def inspect_copy(name, database, source, target, batch, action, identity):
    from google.cloud import firestore

    if action not in {"inspect", "clear"}:
        raise ValueError("Unrecognized restore action")
    apply = action == "clear"
    require_quarantine(source, target, database, batch)
    physical = database_name(database, batch)
    client = firestore.Client(project=target, database=physical)
    try:
        if name == "agent-hub" and database == "agent-hub":
            from app.erase_account import inspect_or_erase

            report = inspect_or_erase(client, identity["uid"], apply=apply, isolated_restore=True)
            if report.get("unclassified", 0) or report.get("error"):
                raise ValueError("Restore contains unclassified Hub data")
            return report["remaining"]
        elif name == "portfolio" and database == "portfolio":
            from app.erase_account import account_records
            from app.store import FirestorePortfolioStore

            store = FirestorePortfolioStore(target, physical, client=client)
            return account_records(store, identity["uid"], apply=apply)
        elif name == "config" and database == "(default)":
            from app.erase_preferences import firestore_preferences

            return firestore_preferences(client, identity["uid"], apply=apply)
        elif name == "user" and database in {"user-data", "(default)"}:
            from app.account_erasure import Subject, firestore_erasure

            person = Subject(identity["uid"], identity["email"], identity["googleSubject"])
            counts = firestore_erasure(
                client,
                person,
                apply=apply,
                check_suspension=lambda: require_quarantine(source, target, database, batch),
            )
            return 0 if apply else sum(counts.values())
        else:
            raise ValueError("Unsupported restore target")
    finally:
        client.close()


if __name__ == "__main__":
    try:
        name, database, source, target, batch, action = sys.argv[1:]
        count = inspect_copy(
            name, database, source, target, batch or None, action, json.load(sys.stdin)
        )
        print(json.dumps({"remaining": count}))
    except (KeyboardInterrupt, Exception):
        sys.exit("The isolated restore could not be cleared. Keep it offline.")
