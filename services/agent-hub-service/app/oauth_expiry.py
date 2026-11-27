"""Scheduled disposal of spent OAuth requests and credentials."""

import time
from contextlib import closing

from google.cloud.firestore_v1.base_query import FieldFilter

from folioview_shared.encrypted.errors import ContractError

from .native_transport import USER_AUTHORITY_TRANSITION
from .store import FirestoreHubStore, SQLiteHubStore, StoreUnavailable, document_path

PREFIXES = ("hub_oauth_", "hub_native_oauth_")
CREDENTIALS = ("codes", "access", "refresh", "families")
PAGE = 48


def _pages(store, table, now, *, owners=False):
    # A database cursor advances even when the preceding row is deleted or its deadline moves.
    after = None
    while True:
        if isinstance(store, SQLiteHubStore):
            order = "0" if owners else "json_extract(body,'$.expiresAt')"
            with closing(store.connect()) as db:
                rows = db.execute(
                    f"SELECT path,{order} AS deadline FROM hub_documents "
                    f"WHERE path GLOB ? AND {order} <= ? AND ({order},path) > (?,?) "
                    "ORDER BY deadline,path LIMIT ?",
                    (table + "/*", now, *(after or (-1, "")), PAGE),
                ).fetchall()
        elif isinstance(store, FirestoreHubStore):
            query = store.client.collection(table)
            if not owners:
                query = query.where(filter=FieldFilter("expiresAt", "<=", now)).order_by(
                    "expiresAt"
                )
            query = query.order_by("__name__").select([] if owners else ["expiresAt"]).limit(PAGE)
            if after:
                values = {"__name__": store.client.document(after[1])}
                if not owners:
                    values["expiresAt"] = after[0]
                query = query.start_after(values)
            rows = [
                (row.reference.path, 0 if owners else row.get("expiresAt"))
                for row in query.stream(timeout=15)
            ]
        else:
            raise StoreUnavailable
        if not rows:
            return
        yield [path for path, _ in rows]
        if len(rows) < PAGE:
            return
        after = (rows[-1][1], rows[-1][0])


def _expire_entries(unit, path, field, now, apply):
    row = unit.get(path)
    if not row:
        return 0
    entries = row.get(field)
    if not isinstance(entries, dict):
        raise StoreUnavailable
    kept = {}
    for key, entry in entries.items():
        if not isinstance(entry, dict) or type(entry.get("expiresAt")) is not int:
            raise StoreUnavailable
        if entry["expiresAt"] > now:
            kept[key] = entry
    expired = len(entries) - len(kept)
    if expired and apply:
        # Retain the global admission rate counter and all other accounts' live entries.
        unit.put(path, {**row, field: kept})
    return expired


def _can_disconnect(unit, family):
    # Native transport can expire while the enrolled agent still has a live parent.
    keys = ("ownerSubject", "vaultId", "connectionId", "authorizationId", "familyId")
    if any(not isinstance(family.get(key), str) for key in keys):
        raise StoreUnavailable
    parent = unit.get(
        document_path("hub_oauth_connections", family["ownerSubject"], family["connectionId"])
    )
    if parent is None:
        return False
    if any(parent.get(key) != family[key] for key in ("ownerSubject", "connectionId", "vaultId")):
        raise StoreUnavailable
    return (
        parent["transportKind"] == "persistent_runtime"
        and parent["status"] == "active"
        and parent["authorizationId"] == family["authorizationId"]
    )


def _keep_marker(unit, path, row, minimal, apply):
    if row == minimal:
        return None
    if apply:
        unit.put(path, minimal)
    return "replayRecords"


def _expired_record(unit, prefix, part, path, now, apply):
    row = unit.get(path)
    if row is None:
        return None
    if type(row.get("expiresAt")) is not int:
        raise StoreUnavailable
    if row["expiresAt"] > now:
        return None
    # A consumed code and used refresh token still revoke their live family on replay,
    # even after the presented credential expired. Native token revocation can also
    # disconnect the current family. Keep only what those original checks consume.
    native = prefix == "hub_native_oauth_"
    if part == "families" and (
        not isinstance(row.get("familyId"), str)
        or not isinstance(row.get("ownerSubject"), str)
        or document_path(prefix + part, row["familyId"]) != path
    ):
        raise StoreUnavailable
    if native and part == "families" and _can_disconnect(unit, row):
        keep = {
            "ownerSubject",
            "vaultId",
            "connectionId",
            "authorizationId",
            "familyId",
            "expiresAt",
            USER_AUTHORITY_TRANSITION,
        }
        minimal = {key: value for key, value in row.items() if key in keep}
        return _keep_marker(unit, path, row, {**minimal, "revoked": True}, apply)
    needs_family = part == "refresh" or (native and part == "access")
    if part == "codes":
        if type(row.get("used")) is not bool:
            raise StoreUnavailable
        needs_family = row["used"]
    if part == "refresh" and type(row.get("used")) is not bool:
        raise StoreUnavailable
    if needs_family:
        context = row.get("context") if part == "codes" else row
        if (
            not isinstance(context, dict)
            or not isinstance(context.get("familyId"), str)
            or not isinstance(context.get("ownerSubject"), str)
        ):
            raise StoreUnavailable
        family = unit.get(document_path(prefix + "families", context["familyId"]))
        if family is not None and (
            family.get("familyId") != context["familyId"]
            or family.get("ownerSubject") != context["ownerSubject"]
            or type(family.get("expiresAt")) is not int
        ):
            raise StoreUnavailable
        if family is not None and (
            family["expiresAt"] > now
            or (native and part != "codes" and _can_disconnect(unit, family))
        ):
            binding = {key: context[key] for key in ("familyId", "ownerSubject")}
            minimal = {
                "resource": row["resource"],
                "client_id": row["client_id"],
                # A compacted record can never authorize use; this is its next disposal date.
                "expiresAt": family["expiresAt"],
            }
            if part == "codes":
                minimal.update(used=True, context=binding)
            else:
                minimal.update(**binding, scope=row["scope"], revoked=True)
                if part == "refresh":
                    minimal["used"] = row["used"]
            return _keep_marker(unit, path, row, minimal, apply)
    if apply:
        unit.delete(path)
    return "expiredRecords"


def process_oauth_expiry(store, *, apply, clock=time.time):
    now = int(clock())
    counts = {"expiredEntries": 0, "expiredRecords": 0, "replayRecords": 0, "reviewRequired": 0}
    for prefix in PREFIXES:
        try:
            path = document_path(prefix + "pending", "pool")
            counts["expiredEntries"] += store.transact(
                lambda unit, path=path: _expire_entries(unit, path, "entries", now, apply)
            )
        except (ContractError, StoreUnavailable):
            counts["reviewRequired"] += 1
        for part in CREDENTIALS:
            for paths in _pages(store, prefix + part, now):
                for path in paths:
                    try:
                        change = store.transact(
                            lambda unit, path=path, prefix=prefix, part=part: _expired_record(
                                unit, prefix, part, path, now, apply
                            )
                        )
                        if change:
                            counts[change] += 1
                    except (ContractError, KeyError, StoreUnavailable):
                        counts["reviewRequired"] += 1
    # Both transports share this owner directory. Expired consent-attempt history is
    # ancillary; the connection IDs and monotonic authorization generations stay intact.
    for paths in _pages(store, "hub_oauth_owners", now, owners=True):
        for path in paths:
            try:
                counts["expiredEntries"] += store.transact(
                    lambda unit, path=path: _expire_entries(unit, path, "attempts", now, apply)
                )
            except (ContractError, StoreUnavailable):
                counts["reviewRequired"] += 1
    return counts
