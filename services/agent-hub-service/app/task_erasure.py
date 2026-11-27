"""Paged permanent erasure of one authenticated task, including its indirect records."""

from folioview_shared.encrypted.crypto import _signed_parts
from folioview_shared.encrypted.jsonutil import strict_json_loads

from .store import StoreUnavailable, document_path
from .task_lifecycle import lifecycle_index, lifecycle_path
from .tasks import _index

# References are removed before matching parent records. Older sparse records whose
# attribution cannot be verified are reported for review, never guessed.
SCANS = (
    ("hub_preparation_objects", "ownerSubject"),
    ("hub_run_components", "ownerSubject"),
    ("hub_run_proofs", "ownerSubject"),
    ("hub_result_revisions", "ownerSubject"),
    ("hub_oauth_codes", "context.ownerSubject"),
    ("hub_oauth_access", "ownerSubject"),
    ("hub_oauth_refresh", "ownerSubject"),
    ("hub_oauth_families", "ownerSubject"),
    ("hub_center_operations", "taskId"),
    ("hub_center_intents", "taskId"),
    ("hub_center_preparations", "request.taskId"),
    ("hub_center_plan_operations", "request.taskId"),
    ("hub_persistent_plan_operations", "receipt.taskId"),
    ("hub_persistent_result_state_operations", "metadata.taskId"),
    ("hub_persistent_results", "context.ownerSubject"),
    ("hub_persistent_publications", "context.ownerSubject"),
    ("hub_task_operations", "ownerSubject"),
    ("hub_task_versions", "ownerSubject"),
    ("hub_preparations", "ownerSubject"),
    ("hub_runs", "ownerSubject"),
    ("hub_persistent_runs", "identity.ownerSubject"),
    # The former cleanup rewrote some rows with a different member carrying owner identity.
    ("hub_persistent_publications", "ownerSubject"),
    ("hub_persistent_runs", "ownerSubject"),
)
SCAN_FIELDS = frozenset(SCANS) | {
    ("hub_results", "ownerSubject"),
    ("hub_persistent_runs", "ownerUid"),
}
PHASES = ("shared_pages", *SCANS, "task_pages", "foreground_heads", "versions", "finish")
REVIEW = object()


def erased_key(owner, vault, task):
    return document_path("hub_erased_task_keys", owner, vault, task)


def _belongs(unit, collection, path, row, owner, vault, task):
    """Authenticate attribution by same-owner parent, stored scope or recomputing the hashed key."""
    if row.get("retiredTaskContent"):
        return row.get("ownerSubject") == owner and (row.get("vaultId"), row.get("taskId")) == (
            vault,
            task,
        )
    if collection == "hub_preparation_objects":
        if "vaultId" in row and "taskId" in row:
            return (row["vaultId"], row["taskId"]) == (vault, task)
        parent = unit.get(document_path("hub_preparations", owner, row["preparationId"]))
        if parent is None:
            return REVIEW
        if parent["taskId"] != task:
            return False
        if "carrierJson" in row:
            payload = _signed_parts(strict_json_loads(row["carrierJson"])["signedObject"])[1]
            return payload["context"]["vaultId"] == vault
        return REVIEW
    if collection in {"hub_run_components", "hub_run_proofs", "hub_result_revisions"}:
        if collection == "hub_result_revisions":
            parent = unit.get(document_path("hub_results", owner, row["resultId"]))
            if parent is None:
                return REVIEW
            return (parent["vaultId"], parent["metadata"]["taskId"]) == (vault, task)
        parent = unit.get(document_path("hub_runs", owner, row["runId"]))
        if parent is None:
            return REVIEW
        parent = parent.get("run", parent)
        return (parent["vaultId"], parent["taskId"]) == (vault, task)
    if collection in {"hub_persistent_results", "hub_persistent_publications"}:
        c = row["context"]
        return (c.get("ownerSubject"), c.get("vaultId"), c.get("taskId")) == (owner, vault, task)
    if collection == "hub_persistent_runs":
        m = strict_json_loads(row["manifestJson"])
        return (m["ownerSubject"], m["vaultId"], m["taskId"]) == (owner, vault, task)
    if collection == "hub_task_versions":
        return (row["metadata"]["vaultId"], row["metadata"]["taskId"]) == (vault, task)
    if collection == "hub_task_operations":
        return (row["vaultId"], row["taskId"]) == (vault, task)
    if collection == "hub_runs":
        return (row["run"]["vaultId"], row["run"]["taskId"]) == (vault, task)
    if collection == "hub_preparations":
        if row["taskId"] != task:
            return False
        connection = unit.get(document_path("hub_oauth_connections", owner, row["connectionId"]))
        if connection is None or connection.get("ownerSubject") != owner:
            return REVIEW
        return connection.get("vaultId") == vault
    if collection.startswith("hub_oauth_"):
        data = row["context"] if collection == "hub_oauth_codes" else row
        return data.get("vaultId") == vault and task in data.get("grantRefs", {})
    if collection == "hub_center_intents":
        return path == document_path(collection, owner, vault, task, row["requestId"])
    if collection == "hub_center_operations":
        op = row.get("operationId") or (row.get("receipt") or {}).get("operationId")
        return REVIEW if op is None else path == document_path(collection, owner, vault, op)
    if collection == "hub_center_preparations":
        from .task_center import preparation_path

        req = row["request"]
        return path == preparation_path(
            owner,
            vault,
            task,
            req["binding"]["assignmentId"],
            req["baseTriggerId"],
            kind=row.get("kind", "legacy_unknown"),
        )
    if collection == "hub_center_plan_operations":
        req = row["request"]
        return path == document_path(
            collection, owner, vault, row["identity"]["connectionId"], req["operationId"]
        )
    if collection == "hub_persistent_plan_operations":
        receipt = row["receipt"]
        return path == document_path(
            collection, owner, vault, receipt["connectionId"], receipt["operationId"]
        )
    if collection == "hub_persistent_result_state_operations":
        ident = row["metadata"]["resultId"]
        parent = unit.get(document_path("hub_persistent_results", owner, vault, ident))
        if parent is None or parent["context"]["taskId"] != task:
            return False
        if "operationId" not in row:
            # The result association alone cannot prove a legacy operation's
            # owner if its hashed document key cannot be reconstructed.
            from .account_writes import index_path

            claim = unit.get(index_path(path))
            return True if claim == {"ownerSubject": owner, "target": str(path)} else REVIEW
        return path == document_path(collection, owner, vault, ident, row["operationId"])
    raise StoreUnavailable


def _remove_record(unit, collection, path, row, owner, vault, task):
    if row.get("retiredTaskContent"):
        unit.delete(path)
        return
    if collection.startswith("hub_oauth_"):
        data = row["context"] if collection == "hub_oauth_codes" else row
        cleaned = {**data, "grantRefs": {k: v for k, v in data["grantRefs"].items() if k != task}}
        unit.put(path, {**row, "context": cleaned} if collection == "hub_oauth_codes" else cleaned)
        return
    if collection == "hub_persistent_results":
        c = row["context"]
        unit.delete(document_path("hub_persistent_result_content", owner, vault, c["objectId"]))
        unit.delete(
            document_path(
                "hub_persistent_result_operations",
                owner,
                vault,
                c["connectionId"],
                c["stableOperationId"],
            )
        )
    elif collection == "hub_persistent_runs":
        m = strict_json_loads(row["manifestJson"])
        unit.delete(
            document_path(
                "hub_persistent_run_operations",
                owner,
                vault,
                m["connectionId"],
                m["stableOperationId"],
            )
        )
    elif collection == "hub_center_preparations":
        unit.delete(document_path("hub_center_triggers", owner, vault, task, row["triggerId"]))
    elif collection == "hub_runs":
        r = row["run"]
        unit.delete(
            document_path(
                "hub_run_indexes",
                owner,
                vault,
                r["connectionId"],
                r["authorizationId"],
                r["grantId"],
                task,
            )
        )
        command = strict_json_loads(row["manifestJson"])["signedBeginIntent"]
        op = _signed_parts(command)[1]["stableOperationId"]
        unit.delete(
            document_path(
                "hub_run_operations",
                owner,
                vault,
                r["connectionId"],
                r["authorizationId"],
                r["grantId"],
                task,
                op,
            )
        )
    elif collection == "hub_result_revisions" and "receipt" in row:
        r = row["receipt"]
        head = unit.get(document_path("hub_results", owner, row["resultId"]))
        run = unit.get(document_path("hub_runs", owner, head["runId"]))
        if run and "run" in run:
            from .results import ResultService

            unit.delete(ResultService._operation_path(None, run, r["stableOperationId"]))
    unit.delete(path)


def _shared_page(unit, owner, vault, task, after):
    from .persistent_results import PersistentResultService, result_path

    if after is None:
        head = unit.get(document_path("hub_persistent_result_indexes", owner, vault))
        if head is None:
            return None
        after = head["pageId"]
    page = PersistentResultService._page(None, unit, owner, vault, after)
    ids = page["resultIds"]
    paths = {r: result_path(owner, vault, r) for r in ids if r is not None}
    rows = unit.get_many(tuple(paths.values()))
    new = []
    for ident in ids:
        if ident is None:
            new.append(None)
            continue
        record = rows[paths[ident]]
        if record is None:
            raise StoreUnavailable
        c = record["context"]
        if (c["ownerSubject"], c["vaultId"], c["objectId"]) != (owner, vault, ident):
            raise StoreUnavailable
        new.append(None if c["taskId"] == task else ident)
    if ids != new:
        path = document_path("hub_persistent_result_pages", owner, vault, after)
        head_path = document_path("hub_persistent_result_indexes", owner, vault)
        if (
            not any(new)
            and len(_index(unit, owner, vault)["tasks"]) == 1
            and unit.get(head_path) == {"pageId": after}
        ):
            unit.delete(path)
            if page["previous"] is None:
                unit.delete(head_path)
            else:
                unit.put(head_path, {"pageId": page["previous"]})
        else:
            unit.put(path, {**page, "resultIds": new})
    return page["previous"]


def _task_page(unit, owner, vault, task, after):
    from .task_center_results import index_path, page_path, stored_page

    if after is None:
        head = unit.get(index_path(owner, vault, task))
        if head is None:
            return None
        after = head["pageId"]
    page = stored_page(unit, owner, vault, task, after)
    unit.delete(page_path(owner, vault, task, after))
    if page["previous"] is None:
        unit.delete(index_path(owner, vault, task))
    return page["previous"]


def _version_page(unit, owner, vault, task, after):
    from .tasks import _paths

    last = _index(unit, owner, vault)["tasks"][task]["taskVersion"]
    first = 1 if after is None else int(after) + 1
    stop = min(last, first + 3)
    for version in range(first, stop + 1):
        unit.delete(document_path("hub_task_deliveries", owner, vault, task, str(version)))
        unit.delete(_paths(owner, vault, task, version))
    return str(stop) if stop < last else None


def _finish(unit, owner, vault, task, row, *, review):
    from .task_center import assignment_path, task_path
    from .task_upload_cancellations import ledger_path
    from .tasks import _paths

    index = _index(unit, owner, vault)
    meta = index["tasks"].pop(task)
    for ident in row["assignmentIds"]:
        unit.delete(assignment_path(owner, vault, task, ident))
        unit.delete(document_path("hub_center_plans", owner, vault, task, ident))
    ids = unit.get(document_path("hub_oauth_owners", owner)) or {}
    for ident in ids.get("connectionIds", ()):
        unit.delete(document_path("hub_persistent_plans", owner, vault, ident, task))
        unit.delete(document_path("hub_persistent_task_authorities", owner, vault, task, ident))
        path = document_path("hub_oauth_connections", owner, ident)
        conn = unit.get(path)
        if conn and task in conn.get("grants", {}):
            grants = {k: v for k, v in conn["grants"].items() if k != task}
            unit.put(path, {**conn, "grants": grants})
    pending_path = document_path("hub_oauth_pending", "pool")
    pending = unit.get(pending_path)
    if pending:
        entries = {
            k: v
            for k, v in pending["entries"].items()
            if not (
                v.get("ownerSubject") == owner
                and v.get("vaultId") == vault
                and task in (v.get("prepared") or {}).get("taskIds", [])
            )
        }
        if len(entries) != len(pending["entries"]):
            unit.put(pending_path, {**pending, "entries": entries})
    cursors_path = document_path("hub_inbox_cursors", owner, vault)
    old_cursors = unit.get(cursors_path)
    if old_cursors is not None:
        cursors = {
            k: v for k, v in old_cursors["cursors"].items() if v["query"].get("taskId") != task
        }
        if cursors:
            unit.put(cursors_path, {**old_cursors, "cursors": cursors})
        else:
            unit.delete(cursors_path)
    ledger = unit.get(ledger_path(owner, vault))
    if ledger is not None:
        records = {
            k: v for k, v in ledger["records"].items() if v["receipt"]["target"]["taskId"] != task
        }
        if records:
            unit.put(ledger_path(owner, vault), {**ledger, "records": records})
        else:
            unit.delete(ledger_path(owner, vault))
    idx = document_path("hub_task_indexes", owner, vault)
    if index["tasks"]:
        unit.put(idx, {**index, "version": index["version"] - meta["taskVersion"], "cursors": {}})
    else:
        unit.delete(idx)
    lifecycle = lifecycle_index(unit, owner, vault)
    lifecycle["tasks"].pop(task)
    if lifecycle["tasks"]:
        unit.put(lifecycle_path(owner, vault), {**lifecycle, "version": lifecycle["version"] + 1})
    else:
        unit.delete(lifecycle_path(owner, vault))
    unit.delete(_paths(owner, vault, task))
    unit.delete(task_path(owner, vault, task))
    unit.delete(document_path("hub_persistent_task_authorities", owner, vault, task))
    unit.delete(document_path("hub_center_intent_queues", owner, vault, task))
    # Only membership in this hash namespace survives. A delayed signed create
    # may still be valid; neither the task ID nor a command, receipt or owner is stored.
    unit.put(erased_key(owner, vault, task), {"reviewRequired": True} if review else {})


def advance(unit, owner, vault, task, row):
    prev = row.get("cleanup", {})
    if prev.get("format") != 2:
        # Previous versions replaced a run with a tombstone and irreversibly lost
        # its child operation keys. An unproven orphan requires separate review.
        progress = {
            "format": 2,
            "phase": 0,
            "after": None,
            "unresolved": bool(prev.get("phase") or prev.get("after") or prev.get("unresolved")),
        }
    else:
        progress = dict(prev)
    phase = progress["phase"]
    if phase >= len(PHASES):
        return progress
    step = PHASES[phase]
    cursor = progress["after"]
    if step == "shared_pages":
        cursor = _shared_page(unit, owner, vault, task, cursor)
    elif step == "task_pages":
        cursor = _task_page(unit, owner, vault, task, cursor)
    elif step == "versions":
        cursor = _version_page(unit, owner, vault, task, cursor)
    elif step == "finish":
        _finish(unit, owner, vault, task, row, review=progress["unresolved"])
        cursor = None
    elif step == "foreground_heads":
        collection = "hub_results"
        rows = unit.scan_owner(collection, "ownerSubject", owner, after=cursor)
        idx = document_path("hub_result_indexes", owner)
        result_ids = unit.get(idx)
        for path, record in rows:
            if (record["vaultId"], record["metadata"]["taskId"]) != (vault, task):
                continue
            if result_ids and record["resultId"] in result_ids["resultIds"]:
                result_ids["resultIds"].remove(record["resultId"])
            unit.delete(
                document_path("hub_result_state_operations", owner, vault, record["resultId"])
            )
            unit.delete(path)
        if result_ids is not None:
            if result_ids["resultIds"]:
                unit.put(idx, result_ids)
            else:
                unit.delete(idx)
        cursor = rows[-1][0] if len(rows) == 4 else None
    else:
        collection, field = step
        selector = owner if field.endswith("ownerSubject") else task
        rows = unit.scan_owner(collection, field, selector, after=cursor)
        # Determine every association before removing sibling rows in this page.
        matched = [(p, r, _belongs(unit, collection, p, r, owner, vault, task)) for p, r in rows]
        for path, record, match in matched:
            if match is REVIEW:
                progress["unresolved"] = True
            elif match:
                _remove_record(unit, collection, path, record, owner, vault, task)
        cursor = rows[-1][0] if len(rows) == 4 else None
    progress.update(phase=phase + (cursor is None), after=cursor)
    return progress
