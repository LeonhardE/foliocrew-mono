"""Source and account erasure through the signed lifecycle and physical stores."""

import asyncio
import copy
import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from cancellation_fixtures import CANCEL, CancellationFixture
from fixtures import OPERATION, OTHER_UID, SOURCE, UID, HoldingsFixture
from test_authority_sync import projection

from app.erase_account import account_records
from app.erase_account import main as erase_account
from app.erasure import authority_generation, legacy_sources, purge_source
from app.fence_sync import synchronize
from app.holdings import PortfolioService
from app.lifecycle import state_path
from app.store import FirestorePortfolioStore, SQLitePortfolioStore, SQLiteTransaction
from folioview_shared.encrypted.errors import ContractError


class SourceErasureTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = SQLitePortfolioStore(Path(tmp.name) / "portfolio.sqlite3")
        self.service = PortfolioService(self.store, clock=lambda: 1000)
        self.f = CancellationFixture()
        self.f.install(self.service)
        self.other = HoldingsFixture(OTHER_UID)
        self.other.install(self.service)
        self.control = self.other.write(self.service)

    def test_source_erases_ledger_entries_only_for_target_and_rejects_racing_sync(self):
        sibling = copy.copy(self.f)
        sibling.source = "test_second_holdings"
        sibling.resource = {**self.f.resource, "resourceId": sibling.source}
        sibling.install(self.service)
        sibling_id = "synthetic_sibling_cancel_01"
        body, _ = sibling.cancellation(cancellation=sibling_id, operation="synthetic_sibling_op_01")
        sibling_receipt = self.service.cancel_upload(UID, sibling.source, body, sibling_id)
        body, _ = self.f.cancellation()
        self.service.cancel_upload(UID, SOURCE, body, CANCEL)
        document = projection(self.f)
        generation = self.store.transact(authority_generation)
        self.f.mutate(self.service, action="delete")
        self.f.ack(self.service)
        with self.assertRaises(ContractError) as error:
            self.service.synchronize_authority(UID, SOURCE, document, generation=generation)
        self.assertEqual(error.exception.code, "version_conflict")
        self.assertEqual(
            sibling_receipt, self.service.upload_cancellation(UID, sibling.source, sibling_id)
        )
        with closing(sqlite3.connect(self.store.path)) as raw:
            rows = raw.execute(
                "SELECT body FROM portfolio_documents WHERE json_extract(body, '$.ownerSubject')=?",
                (self.f.owner,),
            ).fetchall()
        self.assertNotIn(CANCEL, str(rows))
        self.assertNotIn(OPERATION, str(rows))
        self.assertEqual(self.control, self.service.snapshot(OTHER_UID, SOURCE)["receipt"])

    def test_partial_erasure_resumes_with_saved_ack_across_restart_and_cleans_legacy_rows(self):
        for n in range(1, 13):
            self.f.write(
                self.service,
                revision=n,
                snapshot=f"snapshot_{n}",
                operation=f"synthetic_upload_{n:06d}",
            )
        self.f.mutate(self.service, action="delete")
        deletes = 0
        original = SQLiteTransaction.delete

        def interrupt(unit, path):
            nonlocal deletes
            if path.startswith("portfolio_snapshots/"):
                deletes += 1
                if deletes == 10:
                    raise RuntimeError("synthetic interruption")
            original(unit, path)

        with (
            patch.object(SQLiteTransaction, "delete", new=interrupt),
            self.assertRaises(RuntimeError),
        ):
            self.f.ack(self.service)
        store = SQLitePortfolioStore(self.store.path)
        self.assertEqual(list(legacy_sources(store)), [(self.f.owner, SOURCE)])
        self.assertEqual(
            store.transact(lambda u: u.get(state_path(self.f.owner, SOURCE)))["state"], "deleted"
        )
        self.assertEqual(
            account_records(store, UID), 20
        )  # 4 snapshots, 12 uploads, head/authority/ACK/state
        purge_source(store, self.f.owner, SOURCE, now=7000)
        self.assertEqual(account_records(store, UID), 0)
        self.assertEqual(list(legacy_sources(store)), [])
        self.assertEqual(self.control, self.service.snapshot(OTHER_UID, SOURCE)["receipt"])
        purge_source(store, self.f.owner, SOURCE, now=7001)

    def test_offline_account_erasure_removes_live_and_orphaned_records_only_for_target(self):
        self.f.write(self.service)
        row = {"ownerSubject": self.f.owner, "sourceId": "legacy_orphan", "fingerprint": "old"}
        self.store.transact(lambda u: u.put("portfolio_operations/orphan_test", row))
        self.assertEqual(account_records(self.store, UID), 5)
        self.assertEqual(account_records(self.store, UID, apply=True), 0)
        self.assertEqual(account_records(self.store, UID, apply=True), 0)
        self.assertEqual(account_records(self.store, OTHER_UID), 4)
        self.assertEqual(self.control, self.service.snapshot(OTHER_UID, SOURCE)["receipt"])

    def test_wrong_existing_sqlite_target_cannot_report_a_clean_inventory(self):
        path = Path(self.store.path).with_name("unrelated.db")
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE unrelated (value TEXT)")
        with patch("sys.stdin", io.StringIO(UID)), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                erase_account(["--sqlite", str(path)])
        self.assertEqual(error.exception.code, 2)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(
                db.execute("SELECT name FROM sqlite_master").fetchall(), [("unrelated",)]
            )


@unittest.skipUnless(
    os.getenv("FIRESTORE_EMULATOR_HOST", "").startswith(("127.0.0.1:", "localhost:")),
    "requires the loopback Firestore emulator",
)
class EmulatorErasureTests(unittest.TestCase):
    def test_read_only_inventory_can_verify_a_restored_database(self):
        project = "demo-restored-" + uuid4().hex[:12]
        database = "portfolio-restore-test"
        store = FirestorePortfolioStore(project, database)
        self.addCleanup(store.client.close)
        f = HoldingsFixture()
        service = PortfolioService(store, clock=lambda: 1000)
        f.install(service)
        arguments = ["--project", project, "--database", database]
        result = io.StringIO()
        with patch("sys.stdin", io.StringIO(UID)), redirect_stdout(result):
            self.assertEqual(erase_account(arguments), 0)
        self.assertIn('"remaining": 1', result.getvalue())
        with patch("sys.stdin", io.StringIO(UID)), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                erase_account([*arguments, "--apply"])
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(account_records(store, UID), 1)

    def test_signed_delete_and_account_readback_on_the_firestore_adapter(self):
        store = FirestorePortfolioStore("demo-erasure-" + uuid4().hex[:12], "portfolio")
        self.addCleanup(store.client.close)
        service = PortfolioService(store, clock=lambda: 1000)
        target = CancellationFixture()
        control = HoldingsFixture(OTHER_UID)
        for f in (target, control):
            f.install(service)
            f.write(service)
        body, _ = target.cancellation(operation="synthetic_future_op_01")
        service.cancel_upload(UID, SOURCE, body, CANCEL)
        self.assertEqual(account_records(store, UID), 6)
        target.mutate(service, action="delete")
        with patch("app.holdings.purge_source", side_effect=RuntimeError("synthetic loss")):
            with self.assertRaises(RuntimeError):
                target.ack(service)
        self.assertEqual(list(legacy_sources(store)), [(target.owner, SOURCE)])
        operation = "synthetic_mutation_000001"
        self.assertEqual(service.mutation(UID, SOURCE, operation)["state"], "pending")
        self.assertEqual(list(legacy_sources(store)), [(target.owner, SOURCE)])
        receipt = asyncio.run(
            synchronize(service, UID, SOURCE, operation, lambda: self.fail("unneeded network call"))
        )
        self.assertEqual(receipt["state"], "acknowledged")
        self.assertEqual(account_records(store, UID), 0)
        self.assertEqual(store.transact(authority_generation), 1)
        self.assertEqual(service.snapshot(OTHER_UID, SOURCE)["receipt"]["snapshotId"], "snapshot_1")
        self.assertEqual(account_records(store, OTHER_UID, apply=True), 0)
