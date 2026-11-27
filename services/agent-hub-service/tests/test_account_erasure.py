"""Real multi-owner transactions and administrative restore inventories."""

import os
import unittest
import uuid

from app.account_writes import hold_path
from app.erase_account import DRAIN_SECONDS, inspect_or_erase
from app.store import FirestoreHubStore, document_path
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.identity import owner_key


@unittest.skipUnless(
    os.getenv("FIRESTORE_EMULATOR_HOST", "").startswith("127.0.0.1:"), "loopback emulator"
)
class AccountErasureTests(unittest.TestCase):
    def setUp(self):
        from google.auth.credentials import AnonymousCredentials
        from google.cloud import firestore

        project = "demo-hub-account-" + uuid.uuid4().hex[:9]
        self.client = firestore.Client(
            project=project, database="agent-hub", credentials=AnonymousCredentials()
        )
        self.addCleanup(self.client.close)
        self.store = FirestoreHubStore(project, "agent-hub", client=self.client)
        self.uid = "erasure-fixture"
        self.owner = owner_key(self.uid)
        self.foreign = owner_key("independent-fixture")
        for o in (self.owner, self.foreign):
            self.store.transact(
                lambda unit, o=o: unit.put(
                    document_path("hub_vaults", o), {"ownerSubject": o, "vaultId": "v"}
                )
            )
            self.store.transact(
                lambda unit, o=o: unit.put(
                    document_path("hub_center_intents", o, "v", "t", "op"),
                    {"requestId": "op", "taskId": "t"},
                )
            )
        self.pool = self.client.document(str(document_path("hub_oauth_pending", "pool")))
        self.pool.set(
            {
                "entries": {
                    "mine": {"ownerSubject": self.owner},
                    "foreign": {"ownerSubject": self.foreign},
                    "unbound": {"ownerSubject": None},
                },
                "field": "preserved",
            }
        )

    def check(self, **kwargs):
        return inspect_or_erase(self.client, self.uid, **kwargs)

    def test_live_hold_blocks_native_write_and_drains_without_foreign_loss(self):
        self.assertGreater(self.check()["remaining"], 0)
        result = self.check(apply=True, clock=lambda: 100)
        self.assertEqual(
            result,
            {
                "scope": "agent-hub.account",
                "remaining": 1,
                "unclassified": 0,
                "writeHoldUntil": 100 + DRAIN_SECONDS,
            },
        )
        with self.assertRaises(ContractError):
            self.store.transact(
                lambda unit: unit.put(
                    document_path("hub_agent_identities", self.owner, "v", "a"),
                    {"identity": {"ownerSubject": self.owner}},
                )
            )
        self.store.transact(
            lambda unit: unit.put(
                document_path("hub_center_intents", self.foreign, "v", "t", "other"),
                {"requestId": "other", "taskId": "t"},
            )
        )
        self.assertEqual(self.check(apply=True, clock=lambda: 100 + DRAIN_SECONDS)["remaining"], 0)
        self.assertFalse(self.client.document(hold_path(self.owner)).get().exists)
        self.assertEqual(set(self.pool.get().get("entries")), {"foreign", "unbound"})
        self.assertTrue(
            self.client.document(str(document_path("hub_vaults", self.foreign))).get().exists
        )

    def test_native_write_started_before_freeze_cannot_commit_after_it(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event

        from app.erase_account import hold_writes

        entered, resume = Event(), Event()
        path = document_path("hub_agent_identities", self.owner, "v", "running")

        def pending(unit):
            unit.put(path, {"identity": {"ownerSubject": self.owner}})
            entered.set()
            self.assertTrue(resume.wait(8))

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.store.transact, pending)
            try:
                self.assertTrue(entered.wait(8))
                self.assertTrue(hold_writes(self.client, self.uid, clock=lambda: 100)["writeHold"])
                self.assertTrue(
                    hold_writes(self.client, self.uid, clock=lambda: 10000)["writeHold"]
                )
            finally:
                resume.set()
            with self.assertRaises(ContractError):
                future.result()
        self.assertFalse(self.client.document(path).get().exists)
        self.assertEqual(self.check()["writeHoldUntil"], 100 + DRAIN_SECONDS)

    def test_uncertain_legacy_row_or_ghost_descendant_blocks_receipt(self):
        unknown = self.client.document(
            str(document_path("hub_operations", self.owner, "type", "old"))
        )
        unknown.set({"requestFingerprint": "opaque"})
        ghost = (
            self.client.collection("hub_vaults")
            .document("ghost")
            .collection("old")
            .document("nested")
        )
        ghost.set({"archive": "fixture"})
        plan = self.check(apply=True, isolated_restore=True)
        self.assertGreaterEqual(plan["unclassified"], 2)
        self.assertTrue(
            self.client.document(str(document_path("hub_vaults", self.owner))).get().exists
        )
        unknown.delete()
        ghost.delete()
        self.assertEqual(self.check(apply=True, isolated_restore=True)["remaining"], 0)

    def test_pre_index_signed_task_history_can_be_removed(self):
        from contextlib import closing

        import test_task_center_store as center
        from fixtures import UID

        from app.account_writes import OWNERSHIP
        from app.store import _firestore_document, stored_document

        fixture = center.TaskCenterStoreTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.submit(fixture.begin())
        with closing(fixture.store.connect()) as db:
            paths = [
                p
                for (p,) in db.execute("select path from hub_documents")
                if not p.startswith(OWNERSHIP + "/")
            ]
        rows = fixture.store.transact(lambda unit: [(p, unit.get(p)) for p in paths])
        for path, value in rows:
            physical = stored_document(
                value, path=path, project=self.client.project, database="agent-hub"
            )
            self.client.document(path).set(_firestore_document(physical, path=path))
        plan = inspect_or_erase(self.client, UID)
        self.assertEqual(plan["unclassified"], 0, plan)
        self.assertGreater(plan["remaining"], 30)
        self.assertEqual(
            inspect_or_erase(self.client, UID, apply=True, isolated_restore=True)["remaining"], 0
        )
        self.assertGreater(self.check()["remaining"], 0)
