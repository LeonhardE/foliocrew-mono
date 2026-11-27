"""Process eligible task erasures without an open browser or user credential."""

import argparse
import json
import sys
import time

from folioview_shared.encrypted.errors import ContractError

from .store import StoreUnavailable, get_store
from .task_center import task_path
from .task_lifecycle_service import maintain_task

TASK_COUNTS = ("eligible", "completed", "reviewRequired", "failed")
SOURCE_COUNTS = ("eligible", "completed", "deferred", "failed")
OAUTH_COUNTS = ("expiredEntries", "expiredRecords", "replayRecords", "reviewRequired")


def valid_counts(result, fields):
    return (
        type(result) is dict
        and result.keys() == set(fields)
        and all(type(result[k]) is int and 0 <= result[k] <= sys.maxsize for k in fields)
    )


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
    try:
        store = get_store()
        tasks = process_due(store, apply=apply, clock=clock)
        sources = process_sources(store, apply=apply)
        oauth = process_oauth_expiry(store, apply=apply, clock=clock)
        if not (
            valid_counts(tasks, TASK_COUNTS)
            and valid_counts(sources, SOURCE_COUNTS)
            and valid_counts(oauth, OAUTH_COUNTS)
        ):
            raise ValueError
    except Exception:
        # Storage and protocol exceptions can carry record data. Expose only the job result.
        print('{"status":"review_required"}')
        return 1

    report = {key: tasks[key] for key in TASK_COUNTS}
    report["sources"] = {key: sources[key] for key in SOURCE_COUNTS}
    report["oauth"] = "review_required" if oauth["reviewRequired"] else "ok"
    print(json.dumps(report, sort_keys=True))
    return int(
        bool(
            tasks["failed"]
            or tasks["reviewRequired"]
            or sources["failed"]
            or oauth["reviewRequired"]
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
