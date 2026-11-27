"""Process eligible task erasures without an open browser or user credential."""

import argparse
import json
import time

from folioview_shared.encrypted.errors import ContractError

from .store import StoreUnavailable, get_store
from .task_center import task_path
from .task_lifecycle_service import maintain_task


def process_due(store, *, apply, clock=time.time):
    counts = {"eligible": 0, "completed": 0, "reviewRequired": 0, "failed": 0}
    for status in ("purged", "trashed"):
        cursor = None
        while True:
            records = store.task_retention_candidates(status, after=cursor)
            for path, d in records:
                if d["status"] == "trashed" and d["purgeAfter"] > clock():
                    continue
                owner, vault, task = (d[k] for k in ("ownerSubject", "vaultId", "taskId"))
                if path != task_path(owner, vault, task):
                    counts["failed"] += 1
                    continue
                counts["eligible"] += 1
                if not apply:
                    continue
                try:
                    while True:
                        outcome = store.transact(
                            lambda unit, owner=owner, vault=vault, task=task: maintain_task(
                                unit, owner, vault, task, int(clock())
                            )
                        )
                        if outcome["complete"] or outcome["reviewRequired"]:
                            counts["completed" if outcome["complete"] else "reviewRequired"] += 1
                            break
                except ContractError as exc:
                    # The owner can restore a nonexpired task while a page is listed;
                    # re-read and validate eligibility in every committed transaction.
                    if exc.code not in {"not_found", "version_conflict"}:
                        counts["failed"] += 1
                except StoreUnavailable:
                    counts["failed"] += 1
            if len(records) < 32:
                break
            cursor = records[-1][0]
    return counts


def main(*, clock=time.time):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply eligible task, source and OAuth data cleanup.",
    )
    from .oauth_expiry import process_oauth_expiry
    from .source_erasure import process_sources

    apply = parser.parse_args().apply
    store = get_store()
    counts = process_due(store, apply=apply, clock=clock)
    counts["sources"] = process_sources(store, apply=apply)
    counts["oauth"] = process_oauth_expiry(store, apply=apply, clock=clock)
    print(json.dumps(counts, sort_keys=True))
    return int(
        bool(
            counts["failed"]
            or counts["reviewRequired"]
            or counts["sources"]["failed"]
            or counts["oauth"]["reviewRequired"]
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
