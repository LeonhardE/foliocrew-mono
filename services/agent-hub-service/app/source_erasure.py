"""Erase independently stored copies of a producer-confirmed deleted source incarnation."""

from folioview_shared.encrypted.crypto import _signed_parts
from folioview_shared.encrypted.jsonutil import strict_json_loads

from .fences import _state, fence_path
from .persistent_publications import publication_path, source_path
from .private_authority import transferred_writer
from .private_display_names import name_path, operation_path
from .store import StoreUnavailable, document_path, private_resource_writer_fence_path
from .vaults import remove_source

SCANS = (
    ("hub_private_display_name_operations", "state.ownerSubject"),
    ("hub_private_display_names", "state.ownerSubject"),
    ("hub_persistent_publications", "context.ownerSubject"),
    ("hub_preparation_objects", "ownerSubject"),
    ("hub_run_components", "ownerSubject"),
)


def _matches(table, path, row, owner, ref):
    if table.startswith("hub_private_display_name"):
        state = row["state"]
        if state["ref"] != ref:
            return False
        args = (owner, state["vaultId"], state["rootKeyId"], ref)
        expected = (
            name_path(*args)
            if table == "hub_private_display_names"
            else operation_path(*args, state["stableOperationId"])
        )
    elif table == "hub_persistent_publications":
        context = row["context"]
        if context.get("ref") != ref:
            return False
        expected = publication_path(owner, context["vaultId"], context["stableOperationId"])
    elif table == "hub_preparation_objects":
        if row.get("retiredTaskContent") or row["descriptor"].get("resourceRef") != ref:
            return False
        expected = document_path(table, owner, row["preparationId"], row["descriptor"]["objectId"])
    else:
        if row.get("retiredTaskContent"):
            return False
        payload = _signed_parts(strict_json_loads(row["carrierJson"])["signedObject"])[1]
        if payload["context"]["binding"]["resourceRef"] != ref:
            return False
        expected = document_path(table, owner, row["runId"], str(row["index"]))
    if expected != path:
        raise StoreUnavailable
    return True


def erase_source(store, owner, ref, *, max_pages=None):
    marker = document_path("hub_erased_sources", owner, str(fence_path(owner, ref)))
    pages = 0
    while max_pages is None or pages < max_pages:
        pages += 1

        def step(unit):
            if _state(unit, owner, ref)["state"] != "deleted":
                raise StoreUnavailable
            writer = unit.get(private_resource_writer_fence_path(owner))
            if writer is not None:
                if not isinstance(writer, dict):
                    raise StoreUnavailable
                if writer.get("state") == "frozen":
                    return None  # Preserve the in-flight, signed migration baseline.
                if not writer.get("vaultId") or not transferred_writer(
                    unit, owner, writer["vaultId"]
                ):
                    raise StoreUnavailable
            progress = unit.get(marker)
            if progress == {}:
                return True
            stage = (progress or {}).get("stage", 0)
            cursor = (progress or {}).get("after")
            coll, field = SCANS[stage]
            rows = unit.scan_owner(coll, field, owner, after=cursor)
            for path, row in rows:
                if _matches(coll, path, row, owner, ref):
                    if coll == "hub_persistent_publications":
                        c = row["context"]
                        unit.delete(source_path(owner, c["vaultId"], c["connectionId"], ref))
                    unit.delete(path)
            cursor = rows[-1][0] if len(rows) == 4 else None
            stage += int(cursor is None)
            done = stage == len(SCANS)
            if done:
                vault_path = document_path("hub_vaults", owner)
                vault = unit.get(vault_path)
                if vault is not None:
                    if vault["ownerSubject"] != owner:
                        raise StoreUnavailable
                    updated = remove_source(vault, ref)
                    if updated is not vault:
                        unit.put(vault_path, updated)
            unit.put(marker, {} if done else {"stage": stage, "after": cursor})
            return done

        outcome = store.transact(step)
        if outcome is not False:
            return outcome is True
    return False


def process_sources(store, *, apply):
    result = {"eligible": 0, "completed": 0, "deferred": 0, "failed": 0}
    cursor = None
    while True:
        rows = store.deleted_source_candidates(after=cursor)
        for path, data in rows:
            if path != fence_path(data["ownerSubject"], data["ref"]):
                result["failed"] += 1
                continue
            result["eligible"] += 1
            if apply:
                try:
                    done = erase_source(store, data["ownerSubject"], data["ref"])
                    result["completed" if done else "deferred"] += 1
                except (StoreUnavailable, ValueError, KeyError, TypeError):
                    result["failed"] += 1
        if len(rows) < 32:
            return result
        cursor = rows[-1][0]
