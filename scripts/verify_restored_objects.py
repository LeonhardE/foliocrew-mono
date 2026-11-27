"""Read-only, fail-closed check for old objects in a quarantined Firestore restore."""

import hashlib
import os
from contextlib import ExitStack
from datetime import UTC, datetime

from restore_erased_accounts import database_name, require_quarantine

_GENERATION_PATH = (
    "portfolio_erasure_generation/" + hashlib.sha256(b'["authority-fetch"]').hexdigest()
)


def lineage(source, target, logical, physical, admin_factory=None):
    """Bind the original database incarnation and the quarantine to the same backup."""
    if os.getenv("FIRESTORE_EMULATOR_HOST"):
        if not source.startswith("demo-") or not target.startswith("demo-"):
            raise ValueError("Expected two disposable identities")
        return source, logical, target, physical
    if admin_factory is None:
        from google.cloud.firestore_admin_v1 import FirestoreAdminClient

        admin_factory = FirestoreAdminClient
    with admin_factory() as admin:
        original = admin.get_database(name=f"projects/{source}/databases/{logical}", timeout=20)
        restored = admin.get_database(name=f"projects/{target}/databases/{physical}", timeout=20)
        path = restored.source_info.backup.backup
        if not path or not path.startswith(f"projects/{source}/locations/"):
            raise ValueError("Missing original backup")
        backup = admin.get_backup(name=path, timeout=20)
        if (
            original.name != f"projects/{source}/databases/{logical}"
            or restored.name != f"projects/{target}/databases/{physical}"
            or backup.name != path
            or not original.uid
            or not restored.uid
            or original.uid == restored.uid
            or backup.database != original.name
            or backup.database_uid != original.uid
            or original.delete_time is not None
            or restored.delete_time is not None
        ):
            raise ValueError("Surviving authority or restored database identity changed")
        return original.uid, restored.uid, backup.name


def options(client):
    return {"metadata": client._rpc_metadata, "timeout": 30, "retry": None}


def read_time(client):
    db = client._database_string
    (response,) = client._firestore_api.batch_get_documents(
        request={
            "database": db,
            "documents": [db + "/documents/restore_verification/clock"],
        },
        **options(client),
    )
    point = response.read_time
    return datetime.fromtimestamp(int(point.timestamp()), UTC).replace(
        microsecond=point.microsecond
    )


def walk(client, parent, point):
    api = client._firestore_api
    collections = api.list_collection_ids(
        request={"parent": parent, "read_time": point}, **options(client)
    )
    for name in collections:
        if not name or "/" in name:
            raise ValueError("Unexpected collection name")
        prefix = parent + "/" + name + "/"
        rows = api.list_documents(
            request={
                "parent": parent,
                "collection_id": name,
                "read_time": point,
                "page_size": 100,
                "show_missing": True,
            },
            **options(client),
        )
        for row in rows:
            key = row.name.removeprefix(prefix)
            if not row.name.startswith(prefix) or not key or "/" in key:
                raise ValueError("Unexpected document in inventory")
            # An absent parent can still have live children. Always descend into it.
            if row._pb.HasField("create_time"):
                yield row
            yield from walk(client, row.name, point)


def safe_generation(database, path, row):
    if database != "portfolio" or path != _GENERATION_PATH or set(row.fields) != {"generation"}:
        return False
    value = row._pb.fields["generation"]
    return value.WhichOneof("value_type") == "integer_value" and value.integer_value >= 0


def content(document):
    from google.cloud.firestore_v1.types import Document

    return Document.pb(Document(fields=document.fields)).SerializeToString(deterministic=True)


def check_generation(original, point):
    """The one global counter may differ after isolated erasure, but may never carry user fields."""
    db = original._database_string
    path = db + "/documents/" + _GENERATION_PATH
    (result,) = original._firestore_api.batch_get_documents(
        request={"database": db, "documents": [path], "read_time": point},
        **options(original),
    )
    if result._pb.WhichOneof("result") == "missing" and result.missing == path:
        return
    if result.found.name != path or not safe_generation(
        "portfolio", _GENERATION_PATH, result.found
    ):
        raise ValueError("Unexpected authoritative generation data")


def compare(original, documents, point, counts):
    db = original._database_string
    unseen = dict(documents)
    for entry in original._firestore_api.batch_get_documents(
        request={"database": db, "documents": list(unseen), "read_time": point},
        **options(original),
    ):
        if entry._pb.WhichOneof("result") == "missing":
            unseen.pop(entry.missing)
            counts["missing"] += 1
        else:
            saved = unseen.pop(entry.found.name)
            if content(entry.found) != saved:
                counts["changed"] += 1
        counts["checked"] += 1
    if unseen:
        raise ValueError("Incomplete authoritative comparison")


def verify_copy(source, target, database, batch=None):
    result = {
        "scope": "restore.object_erasure",
        "database": database,
        "status": "blocked",
        "checked": 0,
        "missing": 0,
        "changed": 0,
    }
    try:
        from google.cloud import firestore

        physical = database_name(database, batch)
        require_quarantine(source, target, database, batch)
        before = lineage(source, target, database, physical)
        with ExitStack() as opened:
            current = firestore.Client(project=source, database=database)
            opened.callback(current.close)
            restored = firestore.Client(project=target, database=physical)
            opened.callback(restored.close)
            point = min(read_time(current), read_time(restored))
            prefix = restored._database_string + "/documents/"
            live_prefix = current._database_string + "/documents/"
            pending = {}
            for row in walk(restored, prefix[:-1], point):
                path = row.name.removeprefix(prefix)
                if safe_generation(database, path, row):
                    check_generation(current, point)
                    continue
                key = live_prefix + path
                if key in pending:
                    raise ValueError("Repeated document in inventory")
                pending[key] = content(row)
                if len(pending) == 25:
                    compare(current, pending, point, result)
                    pending.clear()
            if pending:
                compare(current, pending, point, result)
        if before != lineage(source, target, database, physical):
            raise ValueError("Authority changed during inventory")
        if not result["missing"] and not result["changed"]:
            result["status"] = "verified"
    except Exception:  # noqa: BLE001 - any incomplete scan blocks release without disclosing paths.
        result["status"] = "blocked"
    return result
