"""Signed task/report histories erased through the ordinary stores and unattended worker."""

import os
import unittest
import uuid
from contextlib import closing
from types import SimpleNamespace

import test_results as foreground
import test_task_center_store as center
from test_oauth import TASK

from app.store import FirestoreHubStore, document_path
from app.task_lifecycle_service import TaskLifecycleService
from app.task_retention_worker import process_due


class StoreErasureTests(unittest.TestCase):
    def test_maximum_version_history_is_erased_in_bounded_pages(self):
        from unittest.mock import Mock, patch

        from app.task_erasure import _version_page
        from app.tasks import MAX_VERSIONS

        unit = Mock()
        cursor = None
        deleted = set()
        with patch(
            "app.task_erasure._index", return_value={"tasks": {TASK: {"taskVersion": MAX_VERSIONS}}}
        ):
            while True:
                cursor = _version_page(unit, "owner", "vault", TASK, cursor)
                self.assertLessEqual(unit.delete.call_count, 8)
                deleted.update(c.args[0] for c in unit.delete.call_args_list)
                unit.delete.reset_mock()
                if cursor is None:
                    break
        self.assertEqual(len(deleted), 2 * MAX_VERSIONS)

    def test_legacy_foreground_versions_receipts_and_grants(self):
        fixture = foreground.ResultTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.submit()
        fixture.results.revise(
            fixture.token,
            fixture.result_id,
            1,
            fixture.make_carrier(foreground.REVISION_OP, revision=2),
            foreground.REVISION_OP,
        )
        old = fixture.case
        owner = TaskLifecycleService(old.store, clock=lambda: old.now)
        signing = SimpleNamespace(f=old.fix, serial=0, fx=old, owner=owner)
        for action in ("set_rules", "trash"):
            receipt = center.TaskCenterStoreTests.control(signing, action)
            signing.definition = receipt["definition"]
        result = process_due(old.store, apply=True, clock=lambda: signing.definition["purgeAfter"])
        self.assertEqual(result, {"eligible": 1, "completed": 1, "reviewRequired": 0, "failed": 0})
        with closing(old.store.connect()) as db:
            leftover = db.execute(
                "SELECT path FROM hub_documents WHERE body LIKE ? OR body LIKE ?",
                ("%" + TASK + "%", "%" + fixture.result_id + "%"),
            ).fetchall()
            self.assertEqual(leftover, [])
            for collection in (
                "hub_run_operations",
                "hub_result_operations",
                "hub_result_revisions",
                "hub_runs",
                "hub_results",
                "hub_run_proofs",
                "hub_run_components",
                "hub_preparation_objects",
                "hub_preparations",
            ):
                self.assertEqual(
                    db.execute(
                        "SELECT count(*) FROM hub_documents WHERE path LIKE ?", (collection + "/%",)
                    ).fetchone(),
                    (0,),
                    collection,
                )

    def test_source_removal_erases_frozen_inputs_but_preserves_independent_report(self):
        from app.fences import FenceService
        from app.source_erasure import process_sources
        from folioview_shared.encrypted.constants import CONTRACT_VERSION

        fixture = foreground.ResultTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.submit()
        case = fixture.case

        def counts():
            with closing(case.store.connect()) as db:
                return [
                    db.execute(
                        "SELECT count(*) FROM hub_documents WHERE path LIKE ?", (coll + "/%",)
                    ).fetchone()[0]
                    for coll in (
                        "hub_run_components",
                        "hub_preparation_objects",
                        "hub_result_revisions",
                    )
                ]

        before = counts()
        self.assertGreaterEqual(min(before), 1)
        FenceService(case.store, clock=lambda: case.now).invalidate(
            {
                "contractVersion": CONTRACT_VERSION,
                "ownerSubject": case.fix.owner,
                "mutationId": "source_erasure_fixture_01",
                "ref": case.sources.ref,
                "expectedSourceEpoch": 1,
                "newSourceEpoch": 2,
                "reason": "deleted",
            },
            source_service="portfolio",
        )
        self.assertEqual(
            process_sources(case.store, apply=True),
            {"eligible": 1, "completed": 1, "deferred": 0, "failed": 0},
        )
        after = counts()
        self.assertLess(after[0], before[0])
        self.assertLess(after[1], before[1])
        self.assertEqual(after[2], before[2])

    @unittest.skipUnless(
        os.getenv("FIRESTORE_EMULATOR_HOST", "").startswith(("127.0.0.1:", "localhost:")),
        "local Firestore emulator required",
    )
    def test_real_firestore_worker_does_not_mutate_foreign_owner(self):
        # A distinct fictional project name per run prevents collisions between test runs.
        from google.auth.credentials import AnonymousCredentials
        from google.cloud import firestore

        fixture = center.TaskCenterStoreTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.submit(fixture.begin())
        fixture.definition = fixture.control("trash")["definition"]
        project = "demo-hub-erase-" + uuid.uuid4().hex[:10]
        client = firestore.Client(
            project=project, database="agent-hub", credentials=AnonymousCredentials()
        )
        self.addCleanup(client.close)
        store = FirestoreHubStore(project, "agent-hub", client=client)
        with closing(fixture.store.connect()) as db:
            paths = [
                p
                for (p,) in db.execute(
                    "SELECT path FROM hub_documents WHERE path NOT LIKE 'hub_account_ownership/%'"
                )
            ]
        rows = fixture.store.transact(lambda unit: [(p, unit.get(p)) for p in paths])
        control = document_path("hub_task_versions", "other-owner", "other-vault", TASK, "1")
        rows.append(
            (
                control,
                {
                    "ownerSubject": "other-owner",
                    "metadata": {"vaultId": "other-vault", "taskId": TASK},
                    "fixture": "unchanged",
                },
            )
        )
        store.transact(lambda unit: [unit.put(p, b) for p, b in rows])
        result = process_due(store, apply=True, clock=lambda: fixture.definition["purgeAfter"])
        self.assertEqual(result, {"eligible": 1, "completed": 1, "reviewRequired": 0, "failed": 0})
        self.assertEqual(store.transact(lambda unit: unit.get(control)), rows[-1][1])
        self.assertEqual(len(list(client.collection("hub_persistent_result_content").stream())), 0)
        self.assertEqual(len(list(client.collection("hub_center_operations").stream())), 0)
        self.assertEqual(len(list(client.collection("hub_erased_task_keys").stream())), 1)
