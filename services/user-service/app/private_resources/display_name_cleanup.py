"""Erase alias ciphertext and every rename receipt after Portfolio retires its incarnation."""

from google.cloud.firestore_v1.base_query import FieldFilter

from folioview_shared.encrypted.errors import ContractError

from ..resources import FirestoreUserResourceStore, SQLiteUserResourceStore

NAMES = "user_private_display_names"
OPERATIONS = "user_private_display_name_operations"


def erase_retired_names(store, owner, ref, *, apply=True):
    count = 0
    if isinstance(store, SQLiteUserResourceStore):
        with store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for table in (NAMES, OPERATIONS):
                if not db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone():
                    continue
                verb = "DELETE" if apply else "SELECT count(*)"
                result = db.execute(
                    f"{verb} FROM {table} WHERE json_extract(value, '$.state.ownerSubject') = ? "
                    "AND json_extract(value,'$.state.ref.resourceId') = ? "
                    "AND json_extract(value,'$.state.ref.incarnation') = ?",
                    (owner, ref["resourceId"], ref["incarnation"]),
                )
                count += result.rowcount if apply else result.fetchone()[0]
        return count
    if not isinstance(store, FirestoreUserResourceStore):
        raise ContractError("authorization_unavailable")
    for table in (NAMES, OPERATIONS):
        query = store.client.collection(table)
        for field, value in (
            ("state.ownerSubject", owner),
            ("state.ref.resourceId", ref["resourceId"]),
            ("state.ref.incarnation", ref["incarnation"]),
        ):
            query = query.where(filter=FieldFilter(field, "==", value))
        if not apply:
            count += sum(1 for _ in query.select([]).stream(timeout=30))
            continue
        while True:
            rows = list(query.select([]).limit(100).stream(timeout=10))
            if not rows:
                break
            batch = store.client.batch()
            for row in rows:
                batch.delete(
                    row.reference,
                    option=store.client.write_option(last_update_time=row.update_time),
                )
            batch.commit(timeout=10)
            count += len(rows)
    return count
