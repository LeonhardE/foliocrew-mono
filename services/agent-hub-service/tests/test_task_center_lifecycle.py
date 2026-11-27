"""Real signed lifecycle races and retention cleanup, entirely synthetic/local."""

import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest.mock import patch

import test_task_center_store as center_tests
from fixtures import OTHER_UID, UID
from test_oauth import TASK

from app.persistent_execution import run_path
from app.store import document_path
from app.task_lifecycle_service import TaskLifecycleService
from folioview_shared.encrypted.errors import ContractError


class TaskLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fx = center_tests.TaskCenterStoreTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.f = self.fx.f
        self.owner = TaskLifecycleService(self.fx.store, clock=lambda: self.fx.fx.now)
        self.fx.owner = self.owner

    def lifecycle(self, action):
        receipt = self.fx.control(action)
        self.fx.definition = receipt["definition"]
        return receipt

    def test_trash_hides_all_actor_history_and_legacy_task_links_restore_is_inert(self):
        one = self.fx.submit(self.fx.begin())
        pending = self.fx.begin("pending_lifecycle_base_trigger_001")
        self.fx.use(self.fx.second)
        self.fx.submit(self.fx.begin())
        self.lifecycle("trash")
        self.assertEqual(self.fx.p.tasks.list(UID)["items"], [])
        self.assertEqual(self.fx.history.owner_list(UID, self.f.vault)["items"], [])
        for read in [
            lambda: self.fx.p.tasks.get(UID, TASK),
            lambda: self.fx.history.owner_get(UID, self.f.vault, one["resultId"]),
            lambda: self.owner.results(UID, self.f.vault, TASK, {"limit": 20, "cursor": None}),
            lambda: self.fx.submit(pending),
            lambda: self.fx.begin("late_lifecycle_base_trigger_001"),
        ]:
            with self.assertRaises(ContractError):
                read()
        self.assertTrue(self.owner.trash(UID, self.f.vault)["items"][0]["canRestore"])
        self.lifecycle("restore")
        self.assertEqual(
            len(
                self.owner.results(UID, self.f.vault, TASK, {"limit": 20, "cursor": None})["items"]
            ),
            2,
        )
        self.assertEqual(
            self.fx.history.owner_get(UID, self.f.vault, one["resultId"])["receipt"], one
        )
        with self.assertRaises(ContractError):
            self.fx.begin()
        self.assertTrue(
            all(
                not a["plan"]["currentAssignment"]
                for a in self.owner.state(UID, self.f.vault, TASK)["assignments"]
            )
        )

    def test_owner_requests_immediate_purge_while_trash_is_recoverable(self):
        from app.task_retention_worker import process_due

        self.lifecycle("trash")
        self.assertGreater(self.fx.definition["purgeAfter"], self.fx.fx.now)
        receipt = self.lifecycle("purge")
        self.assertEqual(receipt["definition"]["status"], "purged")
        progress = process_due(self.fx.store, apply=True, clock=lambda: self.fx.fx.now)
        self.assertEqual(progress["completed"], 1)
        self.assertEqual(self.owner.trash(UID, self.f.vault)["items"], [])
        self.assertTrue(self.owner.maintenance(UID, self.f.vault, TASK)["complete"])

    def test_original_command_retry_cannot_retrash_or_restore(self):
        original = self.lifecycle("trash")
        packet, op = self.fx.last_signed, self.fx.last_op
        self.lifecycle("restore")
        self.assertEqual(self.owner.command(UID, self.f.vault, TASK, packet, op), original)
        self.assertEqual(len(self.fx.p.tasks.list(UID)["items"]), 1)
        with self.assertRaises(ContractError):
            self.owner.command(OTHER_UID, self.f.vault, TASK, packet, op)

    def test_trash_reads_previously_purged_task_without_reading_retired_envelope(self):
        from app.task_center import task_path
        from app.task_lifecycle import lifecycle_index, lifecycle_path
        from app.tasks import _paths

        self.lifecycle("trash")
        self.assertLess(self.fx.fx.now, self.fx.definition["purgeAfter"])

        def retire(unit):
            owner, vault = self.f.owner, self.f.vault
            path = task_path(owner, vault, TASK)
            row = unit.get(path)
            definition = row["definition"]
            definition.update(
                status="purged",
                schedule=None,
                definitionVersion=definition["definitionVersion"] + 1,
                lifecycleEpoch=definition["lifecycleEpoch"] + 1,
            )
            unit.put(path, row)
            index = lifecycle_index(unit, owner, vault)
            index["tasks"][TASK] = "purged"
            index["version"] += 1
            unit.put(lifecycle_path(owner, vault), index)
            version = definition["taskVersion"]
            unit.put(_paths(owner, vault, TASK, version), {"retiredTaskContent": True})

        self.fx.store.transact(retire)
        item = self.owner.trash(UID, self.f.vault)["items"][0]
        self.assertFalse(item["canRestore"])
        self.assertIsNone(item["envelope"])
        self.assertEqual(item["definition"]["status"], "purged")

    @patch("folioview_shared.encrypted.task_center.TRASH_RETENTION_SECONDS", 10)
    def test_restore_deadline_erases_storage_and_receipts_and_preserves_other_data(self):
        saved = self.fx.submit(self.fx.begin())
        # Cleanup must not retire another task or Owner's copies.
        from app.tasks import _paths

        original = self.fx.store.transact(
            lambda u: u.get(_paths(self.f.owner, self.f.vault, TASK, 1))
        )
        foreign = {**original, "ownerSubject": "synthetic_foreign_owner"}
        foreign_path = _paths("synthetic_foreign_owner", self.f.vault, TASK, 1)
        other = {**original, "metadata": {**original["metadata"], "taskId": "another_task"}}
        other_path = _paths(self.f.owner, self.f.vault, "another_task", 1)
        self.fx.store.transact(lambda u: [u.put(foreign_path, foreign), u.put(other_path, other)])
        self.lifecycle("trash")
        self.fx.fx.now = self.fx.definition["purgeAfter"]
        with self.assertRaises(ContractError):
            self.lifecycle("restore")
        with self.assertRaises(ContractError):
            self.owner.maintenance(OTHER_UID, self.f.vault, TASK)
        for _ in range(100):
            progress = self.owner.maintenance(UID, self.f.vault, TASK)
            if progress["complete"]:
                break
        self.assertTrue(progress["complete"])
        self.assertEqual(self.fx.store.transact(lambda u: u.get(other_path)), other)
        self.assertEqual(self.fx.store.transact(lambda u: u.get(foreign_path)), foreign)
        self.assertEqual(progress, self.owner.maintenance(UID, self.f.vault, TASK))
        blob = self.fx.store.transact(
            lambda u: u.get(
                document_path(
                    "hub_persistent_result_content", self.f.owner, self.f.vault, saved["resultId"]
                )
            )
        )
        self.assertIsNone(blob)
        self.assertEqual(self.owner.trash(UID, self.f.vault)["items"], [])
        self.assertEqual(self.fx.history.owner_list(UID, self.f.vault)["items"], [])
        with closing(self.fx.store.connect()) as db:
            for collection in (
                "hub_center_operations",
                "hub_center_assignments",
                "hub_center_tasks",
                "hub_center_triggers",
                "hub_center_preparations",
                "hub_center_result_pages",
                "hub_persistent_results",
                "hub_persistent_result_operations",
                "hub_persistent_run_operations",
                "hub_persistent_runs",
                "hub_persistent_plans",
                "hub_task_operations",
                "hub_task_indexes",
                "hub_center_lifecycle",
                "hub_persistent_result_pages",
                "hub_persistent_result_indexes",
            ):
                with self.subTest(collection=collection):
                    self.assertEqual(
                        db.execute(
                            "select count(*) from hub_documents where path like ?",
                            (collection + "/%",),
                        ).fetchone(),
                        (0,),
                    )
            self.assertEqual(
                db.execute(
                    "select count(*) from hub_documents where path like ?",
                    ("hub_persistent_publications/%",),
                ).fetchone(),
                (2,),
            )
        # The independently encrypted shared source is retained for other tasks.
        with self.assertRaises(ContractError):
            self.fx.history.owner_get(UID, self.f.vault, saved["resultId"])
        with self.assertRaisesRegex(ContractError, "not_found"):
            self.fx.p.create_task()

    def test_worker_claims_only_expired_or_signed_purges_and_resumes_after_interrupt(self):
        from app.store import SQLiteHubStore
        from app.task_retention_worker import process_due

        self.fx.submit(self.fx.begin())
        self.lifecycle("trash")

        def clock():
            return self.fx.fx.now

        self.assertEqual(process_due(self.fx.store, apply=True, clock=clock)["eligible"], 0)
        self.fx.fx.now = self.fx.definition["purgeAfter"]
        self.assertEqual(process_due(self.fx.store, apply=False, clock=clock)["eligible"], 1)
        self.assertFalse(self.owner.maintenance(UID, self.f.vault, TASK)["complete"])
        restarted = SQLiteHubStore(self.fx.store.path)
        results = process_due(restarted, apply=True, clock=clock)
        self.assertEqual(results, {"eligible": 1, "completed": 1, "reviewRequired": 0, "failed": 0})
        self.assertEqual(process_due(restarted, apply=True, clock=clock)["eligible"], 0)
        self.assertEqual(self.owner.trash(UID, self.f.vault)["items"], [])

    def test_begin_trash_race_cannot_leave_a_usable_run(self):
        def begin():
            try:
                return self.fx.begin()
            except ContractError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(begin)
            self.lifecycle("trash")
            run = pending.result()
        if run is not None:
            self.assertIsNotNone(
                self.fx.store.transact(
                    lambda u: u.get(run_path(self.f.owner, self.f.vault, run["manifest"]["runId"]))
                )
            )
            with self.assertRaises(ContractError):
                self.fx.submit(run)
        self.assertEqual(self.fx.p.tasks.list(UID)["items"], [])
