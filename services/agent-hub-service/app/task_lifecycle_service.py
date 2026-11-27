"""Owner trash review and resumable, request-driven retirement of expired copies."""

from bisect import bisect_right

from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.identity import owner_key

from .task_center import definition_row, task_path
from .task_center_results import TaskCenterResultService
from .task_erasure import PHASES, advance, erased_key
from .task_lifecycle import lifecycle_index
from .tasks import _index, _response


class TaskLifecycleService(TaskCenterResultService):
    def command(self, uid, vault, task, signed, operation):
        receipt = super().command(uid, vault, task, signed, operation)
        if (receipt.get("definition") or {}).get("status") == "purged":
            self.store.transact(
                lambda unit: maintain_task(unit, owner_key(uid), vault, task, self.now())
            )
        return receipt

    def trash(self, uid, vault, *, cursor=None):
        if cursor is not None:
            from folioview_shared.encrypted.schema import validate_schema

            validate_schema("Identifier", cursor)
        user_scope = self.user_vaults.read(uid, vault)

        def read(unit):
            owner = owner_key(uid)
            v, _ = self._vault_registry(unit, owner, vault, user_scope)
            index = _index(unit, owner, vault)
            items = []
            states = lifecycle_index(unit, owner, vault)["tasks"]
            ids = sorted(t for t, status in states.items() if status != "active")
            # A previous page may have been permanently erased in the meantime.
            start = 0 if cursor is None else bisect_right(ids, cursor)
            chosen = ids[start : start + 1]
            for task in chosen:
                status = states[task]
                if status == "active":
                    continue
                row = definition_row(unit, owner, vault, task)
                d = row["definition"]
                cleanup = row.get("cleanup", {})
                expired = status == "purged" or self.now() >= d["purgeAfter"]
                items.append(
                    {
                        "taskId": task,
                        "definition": d,
                        "canRestore": status == "trashed" and not expired,
                        "cleanupState": "review_required"
                        if cleanup.get("format") == 2
                        and cleanup.get("phase") == len(PHASES)
                        and cleanup.get("unresolved")
                        else "pending",
                        "envelope": _response(
                            unit, owner, v, task, index["tasks"][task]["taskVersion"]
                        )
                        if not expired
                        else None,
                    }
                )
            return {
                "contractVersion": CONTRACT_VERSION,
                "items": items,
                "nextCursor": chosen[-1] if start + len(chosen) < len(ids) else None,
            }

        return self.store.transact(read)

    def maintenance(self, uid, vault, task):
        user_scope = self.user_vaults.read(uid, vault)

        def write(unit):
            from .vaults import identifier

            identifier(task)
            owner = owner_key(uid)
            self._vault_registry(unit, owner, vault, user_scope)
            return maintain_task(unit, owner, vault, task, self.now())

        return self.store.transact(write)


def maintain_task(unit, owner, vault, task, now):
    fence = unit.get(erased_key(owner, vault, task))
    if fence is not None:
        review = fence.get("reviewRequired", False)
        return {
            "contractVersion": CONTRACT_VERSION,
            "complete": not review,
            "reviewRequired": review,
            "phase": len(PHASES),
        }
    row = definition_row(unit, owner, vault, task)
    if row is None:
        raise ContractError("not_found")
    d = row["definition"]
    if d["status"] != "purged" and (d["status"] != "trashed" or now < d["purgeAfter"]):
        raise ContractError("version_conflict")
    state = advance(unit, owner, vault, task, row)
    done = state["phase"] == len(PHASES)
    if not done:
        unit.put(task_path(owner, vault, task), {**row, "cleanup": state})
    return {
        "contractVersion": CONTRACT_VERSION,
        "complete": done and not state["unresolved"],
        "reviewRequired": done and state["unresolved"],
        "phase": state["phase"],
    }
