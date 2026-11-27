"""Task visibility, lifecycle epochs and Owner restore eligibility."""

from folioview_shared.encrypted.errors import ContractError

from .store import StoreUnavailable, document_path


def lifecycle_path(owner, vault):
    return document_path("hub_center_lifecycle", owner, vault)


def lifecycle_index(unit, owner, vault):
    row = unit.get(lifecycle_path(owner, vault))
    if row is None:
        return {"version": 0, "tasks": {}}
    if (
        set(row) != {"version", "tasks"}
        or type(row["version"]) is not int
        or row["version"] < 0
        or type(row["tasks"]) is not dict
        or any(s not in {"active", "trashed", "purged"} for s in row["tasks"].values())
    ):
        raise StoreUnavailable
    return row


def require_visible(unit, owner, vault, task, *, legacy_writer=False):
    state = lifecycle_index(unit, owner, vault)["tasks"].get(task)
    if state not in {None, "active"} or (legacy_writer and state is not None):
        raise ContractError("not_found")


def visible_metadata(unit, owner, vault, rows):
    states = lifecycle_index(unit, owner, vault)["tasks"]
    return [row for row in rows if states.get(row["taskId"], "active") == "active"]
