"""Register verified erasures, clear application records, and check quarantined restores."""

import argparse
import fcntl
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import UUID, uuid4

from restore_erased_accounts import backup_time, require_quarantine

ROOT = Path(__file__).resolve().parents[1]
# Include the database used by User before the move to its dedicated database.
TARGETS = (
    ("agent-hub", "agent-hub", "app.erase_account"),
    ("portfolio", "portfolio", "app.erase_account"),
    ("config", "(default)", "app.erase_preferences"),
    ("user", "user-data", "app.account_erasure"),
    ("user", "(default)", "app.account_erasure"),
)


class Incomplete(Exception):
    pass


def register_identity(project, uid, email, *, require_disabled):
    import firebase_admin
    from firebase_admin import auth

    if os.getenv("FIREBASE_AUTH_EMULATOR_HOST") or os.getenv("FIRESTORE_EMULATOR_HOST"):
        raise Incomplete("Live identity verification requires matched cloud endpoints.")
    app = firebase_admin.initialize_app(options={"projectId": project, "httpTimeout": 10})
    try:
        record = auth.get_user(uid, app=app)
        google = [p for p in record.provider_data if p.provider_id == "google.com"]
        if (
            record.uid != uid
            or not record.email_verified
            or len(google) != 1
            or not google[0].uid
            or (google[0].email or "").lower() != email
            or (record.email or "").lower() != email
            or (require_disabled and not record.disabled)
        ):
            raise Incomplete(
                "The confirmed identity or its required suspension could not be verified."
            )
        return {"uid": uid, "email": email, "googleSubject": google[0].uid}
    finally:
        firebase_admin.delete_app(app)


@contextmanager
def open_register(path, *, create):
    # A missing or accidentally new register must never green-light a restored database.
    if create:
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
        except FileExistsError:
            pass
    if path.is_symlink() or not path.is_file():
        raise Incomplete("The independent request register is missing.")
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise Incomplete("The independent register must be private to its operator.")
    # Lock a separate, empty file. Locking the database file conflicts with
    # SQLite's native transaction locks on macOS.
    lock_path = path.with_name(path.name + ".lock")
    with os.fdopen(
        os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), "r+b"
    ) as lock:
        info = os.fstat(lock.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise Incomplete("The independent register lock must be private to its operator.")
        fcntl.flock(lock, fcntl.LOCK_EX)
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA secure_delete=ON")
            if create:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, project TEXT NOT NULL,"
                    "uid TEXT NOT NULL, email TEXT NOT NULL, googleSubject TEXT NOT NULL,"
                    "erasedAt REAL, UNIQUE (project,uid))"
                )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS delivery (caseId TEXT NOT NULL, "
                    "message TEXT NOT NULL, PRIMARY KEY(caseId,message))"
                )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS projects (project TEXT PRIMARY KEY, "
                    "cutoff REAL NOT NULL DEFAULT 0)"
                )
            yield db


def register_case(db, project, identity):
    with db:
        db.execute(
            "INSERT INTO cases(id,project,uid,email,googleSubject) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(project,uid) DO NOTHING",
            (str(uuid4()), project, identity["uid"], identity["email"], identity["googleSubject"]),
        )
        row = db.execute(
            "SELECT * FROM cases WHERE project=? AND uid=?", (project, identity["uid"])
        ).fetchone()
        if subject(row) != identity:
            raise Incomplete("An existing request belongs to a different verified identity.")
        db.execute("INSERT OR IGNORE INTO projects(project) VALUES (?)", (project,))
        return row["id"]


def subject(row):
    return {k: row[k] for k in ("uid", "email", "googleSubject")}


def adapter_result(name, module, project, database, body, flags):
    command = [sys.executable, "-m", module, "--project", project, "--database", database, *flags]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "services/common") + os.pathsep + "."}
    run = subprocess.run(
        command,
        input=body + "\n",
        capture_output=True,
        text=True,
        cwd=ROOT / "services" / (name + "-service"),
        env=env,
    )
    if run.returncode:
        raise Incomplete(
            f"{name}/{database}: operation incomplete. Resolve the adapter failure and retry."
        )
    return json.loads(run.stdout)


def service_count(target, project, identity, *, apply=False, restored=False):
    name, database, module = target
    flags = []
    if apply:
        flags.append("--apply")
    if name == "user":
        data = dict(identity)
        if restored:
            flags.append("--restore-inventory")
        else:
            del data["googleSubject"]
        body = json.dumps(data)
    else:
        body = identity["uid"]
    label = f"{name}/{database}"
    try:
        value = adapter_result(name, module, project, database, body, flags)
        if name == "user":
            mode = "restore-inventory" if restored else ("apply" if apply else "inventory")
            if (
                value["database"] != database
                or value["mode"] != mode
                or not isinstance(value["matched"], dict)
            ):
                raise ValueError
            counts = list(value["matched"].values())
        else:
            if value["scope"] != ("config.preferences" if name == "config" else name + ".account"):
                raise ValueError
            counts = [value["remaining"]]
        if not all(type(n) is int and n >= 0 for n in counts):
            raise ValueError
        return sum(counts)
    except (TypeError, AttributeError, ValueError, KeyError) as error:
        raise Incomplete(f"{label}: incomplete or invalid adapter verification.") from error


def inventory(project, identity, *, restored=False):
    return {
        f"{name}/{db}": service_count((name, db, module), project, identity, restored=restored)
        for name, db, module in TARGETS
    }


def collect_deliveries(db, row):
    # Save processor locators outside the databases to be cleared; never print them in the run log.
    request = json.dumps({k: row[k] for k in ("uid", "email")})
    with db:
        for name, database, module in TARGETS:
            if name != "user":
                continue
            result = adapter_result(
                name, module, row["project"], database, request, ["--delivery-refs"]
            )
            ids = result.get("providerMessageIds")
            if (
                result.get("database") != database
                or not isinstance(ids, list)
                or not all(isinstance(x, str) and 0 < len(x) <= 512 for x in ids)
            ):
                raise Incomplete("Incomplete processor reference inventory.")
            db.executemany(
                "INSERT OR IGNORE INTO delivery VALUES (?,?)", ((row["id"], x) for x in ids)
            )


def erase_live(db, row):
    project, identity = row["project"], subject(row)
    checked = register_identity(project, identity["uid"], identity["email"], require_disabled=True)
    if identity != checked:
        raise Incomplete("The current Google identity differs from the request.")
    # Verify each target is reachable before removing any ownership information. On retry,
    # repeat the scans, including services that finished on an earlier invocation.
    inventory(project, identity)
    hub, *producers = TARGETS
    name, database, module = hub
    hold = adapter_result(name, module, project, database, identity["uid"], ["--hold-writes"])
    if hold.get("scope") != "agent-hub.account" or hold.get("writeHold") is not True:
        raise Incomplete("Hub has not verified the account write hold.")
    collect_deliveries(db, row)
    # Keep the consumer fenced until its upstream writers, outboxes and private
    # data have been removed. A retry reuses the hold and verifies each scope.
    for target in (*producers, hub):
        remaining = service_count(target, project, identity, apply=True)
        # User reports the rows its operation matched, including ones just erased.
        if target[0] == "user":
            remaining = service_count(target, project, identity)
        if remaining:
            raise Incomplete(f"{target[0]}/{target[1]} still has records. Retry the open case.")
    counts = inventory(project, identity)
    if any(counts.values()):
        raise Incomplete("Application records remain after verification.")
    with db:
        db.execute("UPDATE cases SET erasedAt=? WHERE id=?", (verified_time(project), row["id"]))
    return counts


def verified_time(project):
    from google.cloud import firestore

    database_times = []
    for database in sorted({t[1] for t in TARGETS}):
        client = firestore.Client(project=project, database=database)
        try:
            # Server read time after the independent scans, without creating a marker.
            stamp = (
                client.collection("erasure_verification")
                .document(uuid4().hex)
                .get(field_paths=[], retry=None, timeout=15)
                .read_time
            )
            database_times.append(stamp.timestamp())
        finally:
            client.close()
    return max(database_times)


def check_restore_age(source_project, restored_project, cutoff, batch=None):
    if os.getenv("FIRESTORE_EMULATOR_HOST"):
        raise Incomplete("The emulator cannot attest to a closed case's backup age.")
    for database in sorted({t[1] for t in TARGETS}):
        if backup_time(source_project, restored_project, database, batch) <= cutoff:
            raise Incomplete("The backup predates a completed erasure.")


def restore_adapter(name, database, source, target, batch, action, identity):
    service = ROOT / "services" / (name + "-service")
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(ROOT / "services/common"), str(service)]),
    }
    command = [
        sys.executable,
        str(ROOT / "scripts/restore_erased_accounts.py"),
        name,
        database,
        source,
        target,
        batch or "",
        action,
    ]
    run = subprocess.run(
        command, input=json.dumps(identity), text=True, env=env, capture_output=True, cwd=service
    )
    if run.returncode:
        raise Incomplete(f"Keep restore offline. {name}/{database} could not complete {action}.")
    value = json.loads(run.stdout)["remaining"]
    if type(value) is not int or value < 0:
        raise Incomplete(f"Invalid readback from {name}/{database}.")
    return value


def check_active_accounts(source, target, batch):
    from verify_restored_objects import verify_copy

    for database in sorted({t[1] for t in TARGETS}):
        report = verify_copy(source, target, database, batch)
        if (
            report.get("scope") != "restore.object_erasure"
            or report.get("database") != database
            or report.get("status") != "verified"
            or any(type(report.get(k)) is not int for k in ("checked", "missing", "changed"))
            or report["checked"] < 0
            or report["missing"] != 0
            or report["changed"] != 0
        ):
            raise Incomplete(
                f"Keep restore offline. Active-account content in {database} differs "
                "from the surviving authority or could not be verified."
            )


def restore_check(db, source_project, restored_project, *, scrub=False, batch=None):
    if (source_project == restored_project) != (batch is not None):
        raise Incomplete("Choose a distinct restore project or an isolated native restore batch.")
    cases = db.execute(
        "SELECT * FROM cases WHERE project=? ORDER BY id", (source_project,)
    ).fetchall()
    project = db.execute(
        "SELECT cutoff FROM projects WHERE project=?", (source_project,)
    ).fetchone()
    if not project:
        raise Incomplete("The source project is absent from the request register.")
    for database in sorted({t[1] for t in TARGETS}):
        require_quarantine(source_project, restored_project, database, batch)
    if project["cutoff"]:
        check_restore_age(source_project, restored_project, project["cutoff"], batch)

    for case in cases:
        identity = subject(case)

        def inspect(identity=identity):
            if batch is None:
                return inventory(restored_project, identity, restored=True)
            return {
                f"{name}/{database}": restore_adapter(
                    name, database, source_project, restored_project, batch, "inspect", identity
                )
                for name, database, _ in TARGETS
            }

        counts = inspect()
        if scrub and any(counts.values()):
            for name, database, _ in TARGETS:
                if counts[f"{name}/{database}"]:
                    restore_adapter(
                        name, database, source_project, restored_project, batch, "clear", identity
                    )
            counts = inspect()
        remaining = [key for key, count in counts.items() if count]
        if remaining:
            raise Incomplete(
                f"Keep restore offline. Case {case['id']} has records in {', '.join(remaining)}."
            )
    check_active_accounts(source_project, restored_project, batch)
    return len(cases)


def retire_identity(row):
    if row["erasedAt"] is None:
        raise Incomplete("Verify database removal first.")
    if any(inventory(row["project"], subject(row), restored=True).values()):
        raise Incomplete("Application records remain; keep the identity disabled.")
    import firebase_admin
    from firebase_admin import auth

    try:
        checked = register_identity(row["project"], row["uid"], row["email"], require_disabled=True)
    except auth.UserNotFoundError:
        return
    if checked != subject(row):
        raise Incomplete("The disabled identity differs from the registered case.")
    app = firebase_admin.initialize_app(options={"projectId": row["project"], "httpTimeout": 10})
    try:
        auth.delete_user(row["uid"], app=app)
        try:
            auth.get_user(row["uid"], app=app)
        except auth.UserNotFoundError:
            return
        raise Incomplete("Identity deletion could not be verified.")
    finally:
        firebase_admin.delete_app(app)


def suspend_identity(row):
    import firebase_admin
    from firebase_admin import auth

    if register_identity(
        row["project"], row["uid"], row["email"], require_disabled=False
    ) != subject(row):
        raise Incomplete("Identity differs from the registered case.")
    app = firebase_admin.initialize_app(options={"projectId": row["project"], "httpTimeout": 10})
    try:
        auth.update_user(row["uid"], disabled=True, app=app)
        auth.revoke_refresh_tokens(row["uid"], app=app)
    finally:
        firebase_admin.delete_app(app)
    if register_identity(
        row["project"], row["uid"], row["email"], require_disabled=True
    ) != subject(row):
        raise Incomplete("Identity suspension could not be verified.")


def close_case(db, row, evidence):
    import firebase_admin
    from firebase_admin import auth
    from google.cloud import firestore_admin_v1

    # These destinations can require operator and processor verification. Accept a
    # non-identifying case reference per destination, not an inferred deadline.
    required = {"logs", "backups", "processors", "registerCopies"}
    if (
        not isinstance(evidence, dict)
        or set(evidence) != required
        or not all(
            isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", v)
            for v in evidence.values()
        )
    ):
        raise Incomplete("Provide the four reviewed external evidence references on stdin.")
    if row["erasedAt"] is None or any(
        inventory(row["project"], subject(row), restored=True).values()
    ):
        raise Incomplete("Application deletion has not been verified.")
    if os.getenv("FIREBASE_AUTH_EMULATOR_HOST") or os.getenv("FIRESTORE_EMULATOR_HOST"):
        raise Incomplete("Live closure requires matched cloud endpoints.")
    app = firebase_admin.initialize_app(options={"projectId": row["project"], "httpTimeout": 10})
    try:
        try:
            auth.get_user(row["uid"], app=app)
        except auth.UserNotFoundError:
            pass
        else:
            raise Incomplete("The identity still exists.")
    finally:
        firebase_admin.delete_app(app)
    with firestore_admin_v1.FirestoreAdminClient() as client:
        for database in sorted({t[1] for t in TARGETS}):
            resource = client.get_database(
                name=f"projects/{row['project']}/databases/{database}", timeout=15
            )
            if (
                not resource.earliest_version_time
                or resource.earliest_version_time.timestamp() <= row["erasedAt"]
            ):
                raise Incomplete(f"The historical read window has not cleared for {database}.")
    with db:
        db.execute(
            "UPDATE projects SET cutoff=max(cutoff,?) WHERE project=?",
            (row["erasedAt"], row["project"]),
        )
        db.execute("DELETE FROM delivery WHERE caseId=?", (row["id"],))
        db.execute("DELETE FROM cases WHERE id=?", (row["id"],))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "register",
            "inventory",
            "suspend",
            "erase",
            "retire-identity",
            "close",
            "restore-check",
            "restore-scrub",
        ],
    )
    parser.add_argument("--register", type=Path, required=True)
    parser.add_argument("--project", required=True, help="Verified source project")
    parser.add_argument("--case", type=UUID)
    parser.add_argument("--restored-project", help="Isolated project containing restored databases")
    parser.add_argument(
        "--restore-batch", help="Isolated native backup databases in the source project"
    )
    args = parser.parse_args()
    if args.restore_batch and (not args.restored_project or args.restored_project != args.project):
        parser.error("A native restore batch must use the source project.")
    if any(
        not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", x)
        for x in (args.project, args.restored_project or args.project)
    ):
        parser.error("Supply explicit project IDs.")
    if bool(args.case) != (
        args.action in {"inventory", "suspend", "erase", "retire-identity", "close"}
    ) or bool(args.restored_project) != (args.action in {"restore-check", "restore-scrub"}):
        parser.error(
            "Select one case for inventory/erase, or one isolated project for restore-check."
        )
    with open_register(args.register, create=args.action == "register") as db:
        if args.action == "register":
            line = sys.stdin.buffer.read(2049)
            if len(line) > 2048:
                raise Incomplete("Invalid identity input.")
            request = json.loads(line)
            if (
                not isinstance(request, dict)
                or set(request) != {"uid", "email"}
                or not all(
                    isinstance(s, str) and s and s == s.strip() and not any(ord(c) < 32 for c in s)
                    for s in request.values()
                )
            ):
                raise Incomplete("Supply a verified UID and account email on standard input.")
            identity = register_identity(
                args.project, request["uid"], request["email"].lower(), require_disabled=False
            )
            result = {"case": register_case(db, args.project, identity)}
        elif args.action in {"restore-check", "restore-scrub"}:
            result = {
                "verifiedRestoreCases": restore_check(
                    db,
                    args.project,
                    args.restored_project,
                    scrub=args.action == "restore-scrub",
                    batch=args.restore_batch,
                )
            }
        else:
            row = db.execute(
                "SELECT * FROM cases WHERE id=? AND project=?", (str(args.case), args.project)
            ).fetchone()
            if row is None:
                raise Incomplete("The case is not registered for this project.")
            if args.action == "suspend":
                suspend_identity(row)
                result = {"identityDisabled": True, "caseOpen": True}
            elif args.action == "retire-identity":
                retire_identity(row)
                result = {"identityRemoved": True, "caseOpen": True}
            elif args.action == "close":
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    row = db.execute(
                        "SELECT * FROM cases WHERE id=? AND project=?",
                        (str(args.case), args.project),
                    ).fetchone()
                    if row is None:
                        raise Incomplete("The case is already closed.")
                    close_case(db, row, json.load(sys.stdin))
                result = {"closed": True}
            else:
                counts = (
                    erase_live(db, row)
                    if args.action == "erase"
                    else inventory(args.project, subject(row))
                )
                result = {"scope": "application-databases", "remaining": counts}
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Incomplete as error:
        sys.exit(str(error))
    except (KeyboardInterrupt, Exception):
        sys.exit("Erasure operation incomplete. Verify the register, identity and database access.")
