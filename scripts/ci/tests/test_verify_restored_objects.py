"""Admission checks using the Firestore emulator and synthetic active accounts."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import verify_restored_objects as gate


class LineageTests(unittest.TestCase):
    @patch.dict(os.environ, {"FIRESTORE_EMULATOR_HOST": ""})
    def test_recreated_original_is_not_a_surviving_authority(self):
        factory = MagicMock()
        admin = factory.return_value.__enter__.return_value
        original, restored, backup = Mock(), Mock(), Mock()
        original.name = "projects/demo-authority/databases/portfolio"
        restored.name = "projects/demo-restore/databases/portfolio"
        original.uid, restored.uid, backup.database_uid = (
            "new-original",
            "restored",
            "old-original",
        )
        path = "projects/demo-authority/locations/test/backups/saved"
        restored.source_info.backup.backup = path
        backup.name, backup.database = path, original.name
        original.delete_time = restored.delete_time = None
        admin.get_database.side_effect = [original, restored, original, restored]
        admin.get_backup.return_value = backup
        with self.assertRaises(ValueError):
            gate.lineage("demo-authority", "demo-restore", "portfolio", "portfolio", factory)
        original.uid = "old-original"
        self.assertEqual(
            gate.lineage("demo-authority", "demo-restore", "portfolio", "portfolio", factory),
            ("old-original", "restored", path),
        )


@unittest.skipUnless(
    os.getenv("FIRESTORE_EMULATOR_HOST", "").startswith(("localhost:", "127.0.0.1:")),
    "requires the loopback Firestore emulator",
)
class RestoreObjectEmulatorTests(unittest.TestCase):
    def setUp(self):
        suffix = uuid4().hex[:10]
        self.source, self.target = "demo-auth-" + suffix, "demo-restore-" + suffix

    def clients(self, db):
        from google.cloud import firestore

        clients = [firestore.Client(project=p, database=db) for p in (self.source, self.target)]
        for client in clients:
            self.addCleanup(client.close)
        return clients

    def verify(self, database):
        return gate.verify_copy(self.source, self.target, database)

    def test_restored_deleted_source_task_archive_and_list_are_blocked(self):
        for db, key in (
            ("portfolio", "portfolio_snapshots/old"),
            ("agent-hub", "hub_tasks/old"),
            ("user-data", "archives/owner"),
            ("(default)", "follows/owner"),
        ):
            with self.subTest(db=db):
                live, saved = self.clients(db)
                saved.document(key).set({"items": ["gone", "keep"]})
                for client in (live, saved):
                    client.document("active/sibling").set({"items": ["other owner"]})
                if db in {"user-data", "(default)"}:
                    live.document(key).set({"items": ["keep"]})
                report = self.verify(db)
                self.assertEqual(report["status"], "blocked")
                self.assertEqual(report["checked"], 2)
                self.assertEqual(report["missing"] + report["changed"], 1)
                self.assertTrue(saved.document(key).get().exists)
                if db in {"portfolio", "agent-hub"}:
                    saved.document(key).delete()
                else:
                    saved.document(key).set({"items": ["keep"]})
                self.assertEqual(self.verify(db)["status"], "verified")

    def test_absent_parent_typed_field_and_anonymous_counter(self):
        live, saved = self.clients("portfolio")
        child = "orphan/missing/grandchildren/content"
        saved.document(child).set({"amount": 5.0})
        saved.document(gate._GENERATION_PATH).set({"generation": 3})
        self.assertEqual(self.verify("portfolio")["missing"], 1)
        live.document(child).set({"amount": 5})
        self.assertEqual(self.verify("portfolio")["changed"], 1)
        live.document(child).set({"amount": 5.0})
        self.assertEqual(self.verify("portfolio")["status"], "verified")
        live.document(gate._GENERATION_PATH).set({"generation": 0, "unexpected": "private"})
        self.assertEqual(self.verify("portfolio")["status"], "blocked")
        live.document(gate._GENERATION_PATH).delete()
        saved.document(gate._GENERATION_PATH).set({"generation": 0, "unexpected": "private"})
        self.assertEqual(self.verify("portfolio")["missing"], 1)
        saved.document(gate._GENERATION_PATH).set({"generation": True})
        self.assertEqual(self.verify("portfolio")["missing"], 1)
        saved.document(gate._GENERATION_PATH).set({"generation": 0})
        saved.document(gate._GENERATION_PATH + "/nested/record").set({})
        self.assertEqual(self.verify("portfolio")["missing"], 1)

    def test_unavailable_authority_and_alias_never_pass(self):
        with patch.object(gate, "read_time", side_effect=OSError()):
            self.assertEqual(self.verify("portfolio")["status"], "blocked")
        self.assertEqual(
            gate.verify_copy(self.target, self.target, "portfolio")["status"], "blocked"
        )
