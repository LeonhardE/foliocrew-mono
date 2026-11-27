"""Recover pre-inventory ownership by recomputing exact keys from service relationships."""

from collections import defaultdict

from folioview_shared.encrypted.jsonutil import strict_json_loads

from .persistent_publications import source_path
from .store import document_path

# Only non-content fields needed to reconstruct owner-scoped key arguments.
FIELDS = [
    "assignment.ownerSubject",
    "consent.ownerSubject",
    "slot.ownerSubject",
    "operation.ownerSubject",
    "receipt.definition.ownerSubject",
    "receipt.operationId",
    "receipt.definition.vaultId",
    "receipt.definition.taskId",
    "context.vaultId",
    "context.objectId",
    "context.objectType",
    "context.connectionId",
    "context.stableOperationId",
    "context.ref",
    "definition.vaultId",
    "definition.taskId",
    "identity.vaultId",
    "identity.connectionId",
    "metadata.vaultId",
    "metadata.taskId",
    "connectionId",
    "taskId",
    "requestId",
    "request.baseTriggerId",
    "request.taskId",
    "request.binding.assignmentId",
    "triggerId",
    "kind",
    "assignmentIds",
    "pageId",
    "previous",
    "taskCenter.ownerSubject",
    "taskCenter.taskId",
    "metadata.runId",
]


def recover_paths(rows, claims, initial):
    paths = dict(initial)
    task_scopes = defaultdict(set)
    connections = defaultdict(set)
    pages = defaultdict(set)
    for path, (owner, snap) in rows.items():
        owner = owner or claims.get(path) or paths.get(path)
        if owner is None:
            continue
        row = snap.to_dict()
        coll = snap.reference.parent.id
        for item in (
            row,
            *(row.get(k) or {} for k in ("context", "identity", "definition", "metadata")),
        ):
            vault = item.get("vaultId")
            if vault and item.get("taskId"):
                task_scopes[item["taskId"]].add((owner, vault))
            conn = item.get("connectionId")
            if vault and conn:
                connections[owner, vault].add(conn)

        def add(table, *parts, subject=owner):
            if all(isinstance(v, str) for v in parts):
                paths[str(document_path(table, subject, *parts))] = subject

        if coll == "hub_oauth_connections":
            conn = row["connectionId"]
            add("hub_agent_credential_limits", conn)
            add("hub_persistent_run_quotas", "minute", conn)
            add("hub_persistent_run_quotas", "day", owner)
        elif coll == "hub_persistent_publications":
            c = row["context"]
            if c.get("ref"):
                paths[str(source_path(owner, c["vaultId"], c["connectionId"], c["ref"]))] = owner
        elif coll == "hub_persistent_results":
            c = row["context"]
            add("hub_persistent_result_content", c["vaultId"], c["objectId"])
            add(
                "hub_persistent_result_operations",
                c["vaultId"],
                c["connectionId"],
                c["stableOperationId"],
            )
        elif coll == "hub_center_tasks":
            d = row["definition"]
            t, v = d["taskId"], d["vaultId"]
            for table in (
                "hub_center_result_indexes",
                "hub_persistent_task_authorities",
                "hub_center_intent_queues",
            ):
                add(table, v, t)
            for a in row.get("assignmentIds", ()):
                add("hub_center_assignments", v, t, a)
                add("hub_center_plans", v, t, a)
        elif coll == "hub_persistent_runs":
            # The manifest is public protocol metadata, separate from encrypted content.
            manifest = snap.reference.get(field_paths=["manifestJson"]).to_dict() or {}
            if manifest.get("manifestJson"):
                m = strict_json_loads(manifest["manifestJson"])
                if (
                    m["ownerSubject"] == owner
                    and str(document_path(coll, owner, m["vaultId"], m["runId"])) == path
                ):
                    add(
                        "hub_persistent_run_operations",
                        m["vaultId"],
                        m["connectionId"],
                        m["stableOperationId"],
                    )
    for task, scopes in task_scopes.items():
        for owner, vault in scopes:
            for conn in connections[owner, vault]:
                for table in ("hub_persistent_plans", "hub_persistent_task_authorities"):
                    paths[
                        str(
                            document_path(table, owner, vault, conn, task)
                            if table == "hub_persistent_plans"
                            else document_path(table, owner, vault, task, conn)
                        )
                    ] = owner
            pages[str(document_path("hub_center_result_indexes", owner, vault, task))].add(
                ("hub_center_result_pages", owner, vault, task)
            )
            pages[str(document_path("hub_persistent_result_indexes", owner, vault))].add(
                ("hub_persistent_result_pages", owner, vault)
            )
    # A page is attributable only when an established head or predecessor links to it.
    todo = list(pages.items())
    visited = set()
    while todo:
        path, scopes = todo.pop()
        if path in visited or path not in rows:
            continue
        visited.add(path)
        row = rows[path][1].to_dict()
        following = row.get("pageId") if "_indexes/" in path else row.get("previous")
        for scope in scopes:
            table, owner, *parts = scope
            paths[path] = owner
            if following:
                child = str(document_path(table, owner, *parts, following))
                todo.append((child, {scope}))
    for path, (_, snap) in rows.items():
        coll = snap.reference.parent.id
        if coll != "hub_center_preparations":
            continue
        row = snap.to_dict()
        req = row.get("request", {})
        for owner, vault in task_scopes[req.get("taskId")]:
            task = req["taskId"]
            parts = [owner, vault, task, req["binding"]["assignmentId"]]
            if row.get("kind", "legacy_unknown") != "legacy_unknown":
                parts.append(row["kind"])
            if document_path(coll, *parts, req["baseTriggerId"]) == path:
                paths[path] = owner
                paths[
                    str(document_path("hub_center_triggers", owner, vault, task, row["triggerId"]))
                ] = owner
    return paths
