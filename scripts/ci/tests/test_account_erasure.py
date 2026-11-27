"""Operator regressions for ownership, interruption, and quarantined restore admission."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import account_erasure as erasure
import restore_erased_accounts as restored

try:
    import firebase_admin.auth
    import google.cloud.firestore_admin_v1
except ImportError:
    HAS_ADMIN_SDK = False
else:
    HAS_ADMIN_SDK = bool(firebase_admin.auth and google.cloud.firestore_admin_v1)


class AccountErasureTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(erasure, "require_quarantine"))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "private.db"
        self.db = self.enterContext(erasure.open_register(self.path, create=True))
        self.owner = {
            "uid": "fixture-one",
            "email": "one@example.invalid",
            "googleSubject": "google-one",
        }
        self.control = {**self.owner, "uid": "fixture-two", "googleSubject": "google-two"}
        self.case = erasure.register_case(self.db, "demo-source", self.owner)
        self.row = self.db.execute("SELECT * FROM cases WHERE id=?", (self.case,)).fetchone()

    def test_reregistration_matches_identity_and_missing_register_cannot_pass(self):
        self.assertEqual(self.case, erasure.register_case(self.db, "demo-source", self.owner))
        self.assertNotEqual(self.case, erasure.register_case(self.db, "demo-source", self.control))
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        with self.assertRaises(erasure.Incomplete):
            erasure.register_case(
                self.db, "demo-source", {**self.owner, "googleSubject": "different"}
            )
        with (
            self.assertRaises(erasure.Incomplete),
            erasure.open_register(self.path.with_suffix(".missing"), create=False),
        ):
            pass

    def test_restore_checks_every_account_and_blocks_an_old_copy(self):
        erasure.register_case(self.db, "demo-source", self.control)

        def read(_project, subject, *, restored):
            self.assertTrue(restored)
            return {"config/(default)": int(subject == self.owner)}

        with (
            patch.object(erasure, "inventory", side_effect=read),
            self.assertRaisesRegex(erasure.Incomplete, "Keep restore offline"),
        ):
            erasure.restore_check(self.db, "demo-source", "demo-restored")
        with (
            patch.object(erasure, "inventory", return_value={"config": 0}) as read,
            patch.object(erasure, "check_active_accounts") as check_active,
        ):
            self.assertEqual(erasure.restore_check(self.db, "demo-source", "demo-restored"), 2)
            self.assertEqual(read.call_count, 2)
            check_active.assert_called_once_with("demo-source", "demo-restored", None)
        with self.assertRaises(erasure.Incomplete):
            erasure.restore_check(self.db, "demo-source", "demo-source", scrub=True)
        with self.assertRaises(erasure.Incomplete):
            erasure.restore_check(self.db, "demo-wrong", "demo-restored")

    def test_erase_refuses_partial_inventory_before_any_service_is_cleared(self):
        with (
            patch.object(erasure, "register_identity", return_value=self.owner),
            patch.object(erasure, "inventory", side_effect=erasure.Incomplete()),
            patch.object(erasure, "service_count") as write,
            self.assertRaises(erasure.Incomplete),
        ):
            erasure.erase_live(self.db, self.row)
        write.assert_not_called()

    def test_partial_apply_keeps_private_delivery_locator_and_open_request(self):
        def adapter(name, module, project, database, body, flags):
            if name == "agent-hub":
                self.assertEqual(flags, ["--hold-writes"])
                return {"scope": "agent-hub.account", "writeHold": True}
            self.assertEqual(flags, ["--delivery-refs"])
            return {
                "database": database,
                "providerMessageIds": ["fictional"] if database == "user-data" else [],
            }

        with (
            patch.object(erasure, "register_identity", return_value=self.owner),
            patch.object(erasure, "inventory", return_value={"hub": 2}),
            patch.object(erasure, "adapter_result", side_effect=adapter),
            patch.object(erasure, "service_count", side_effect=[0, erasure.Incomplete()]),
            self.assertRaises(erasure.Incomplete),
        ):
            erasure.erase_live(self.db, self.row)
        self.assertEqual(self.db.execute("SELECT count(*) FROM delivery").fetchone()[0], 1)
        self.assertIsNone(self.db.execute("SELECT erasedAt FROM cases").fetchone()[0])

    def test_incomplete_adapter_and_aged_backup_evidence_fail_closed(self):
        for data in (
            {"scope": "portfolio.account", "remaining": True},
            {"scope": "config.preferences", "remaining": 0},
            {},
        ):
            with (
                patch.object(erasure, "adapter_result", return_value=data),
                self.assertRaises(erasure.Incomplete),
            ):
                erasure.service_count(erasure.TARGETS[1], "demo-source", self.owner)
        self.db.execute("UPDATE projects SET cutoff=1")
        with (
            patch.object(erasure, "check_restore_age", side_effect=erasure.Incomplete()),
            self.assertRaises(erasure.Incomplete),
        ):
            erasure.restore_check(self.db, "demo-source", "demo-restored")

    def test_missing_hub_hold_blocks_all_removals(self):
        with (
            patch.object(erasure, "register_identity", return_value=self.owner),
            patch.object(erasure, "inventory", return_value={"hub": 1}),
            patch.object(erasure, "adapter_result", return_value={"writeHold": False}),
            patch.object(erasure, "service_count") as delete,
            self.assertRaises(erasure.Incomplete),
        ):
            erasure.erase_live(self.db, self.row)
        delete.assert_not_called()

    def test_sources_clear_before_hub_even_when_user_reports_how_many_it_removed(self):
        touches = []

        def count(target, project, subject, *, apply=False):
            touches.append((target[0], target[1], apply))
            return 3 if target[0] == "user" and apply else 0

        with (
            patch.object(erasure, "register_identity", return_value=self.owner),
            patch.object(erasure, "inventory", side_effect=[{"user": 3}, {"user": 0}]),
            patch.object(
                erasure,
                "adapter_result",
                return_value={
                    "scope": "agent-hub.account",
                    "writeHold": True,
                },
            ),
            patch.object(erasure, "collect_deliveries"),
            patch.object(erasure, "service_count", side_effect=count),
            patch.object(erasure, "verified_time", return_value=10),
        ):
            self.assertEqual(erasure.erase_live(self.db, self.row), {"user": 0})
        self.assertEqual(
            touches,
            [
                ("portfolio", "portfolio", True),
                ("config", "(default)", True),
                ("user", "user-data", True),
                ("user", "user-data", False),
                ("user", "(default)", True),
                ("user", "(default)", False),
                ("agent-hub", "agent-hub", True),
            ],
        )
        self.assertEqual(self.db.execute("SELECT erasedAt FROM cases").fetchone()[0], 10)

    def test_retire_identity_requires_verified_absence_in_every_scope(self):
        row = dict(self.row, erasedAt=1.0)
        with (
            patch.object(erasure, "inventory", return_value={"user": 1}),
            patch.object(erasure, "register_identity") as lookup,
            self.assertRaises(erasure.Incomplete),
        ):
            erasure.retire_identity(row)
        lookup.assert_not_called()

    @unittest.skipUnless(HAS_ADMIN_SDK, "Firebase Admin SDK")
    def test_retire_identity_retries_after_lost_firebase_ack(self):
        from firebase_admin.auth import UserNotFoundError

        with (
            patch.object(erasure, "inventory", return_value={"user": 0}),
            patch.object(erasure, "register_identity", side_effect=UserNotFoundError("missing")),
        ):
            erasure.retire_identity(dict(self.row, erasedAt=1.0))

    @unittest.skipUnless(HAS_ADMIN_SDK, "Firestore Admin SDK")
    def test_native_backup_can_only_target_its_own_isolated_database(self):
        with self.assertRaises(ValueError):
            restored.database_name("portfolio", "../portfolio")
        with self.assertRaises(ValueError):
            restored.database_name("unrelated", "batch01")
        backup_path = "projects/demo-source/locations/test/backups/verified"
        client = MagicMock()
        client.get_database.return_value.source_info.backup.backup = backup_path
        client.get_backup.return_value = SimpleNamespace(
            database="projects/demo-source/databases/portfolio",
            snapshot_time=SimpleNamespace(timestamp=lambda: 25),
        )
        with patch("google.cloud.firestore_admin_v1.FirestoreAdminClient") as api:
            api.return_value.__enter__.return_value = client
            self.assertEqual(
                restored.backup_time("demo-source", "demo-source", "portfolio", "batch01"), 25
            )
            client.get_database.assert_called_once_with(
                name="projects/demo-source/databases/erasure-restore-batch01-portfolio",
                timeout=15,
            )
            client.get_backup.return_value.database = "projects/demo-source/databases/user-data"
            with self.assertRaises(ValueError):
                restored.backup_time("demo-source", "demo-source", "portfolio", "batch01")

    @unittest.skipUnless(HAS_ADMIN_SDK, "Firebase and Firestore Admin SDKs")
    def test_case_identity_is_forgotten_only_after_history_and_external_review(self):
        from firebase_admin.auth import UserNotFoundError

        self.db.execute("UPDATE cases SET erasedAt=25")
        self.db.execute("INSERT INTO delivery VALUES (?,?)", (self.case, "private-mail-id"))
        self.db.commit()
        saved = self.db.execute("SELECT * FROM cases WHERE id=?", (self.case,)).fetchone()
        evidence = dict(
            logs="logs-done",
            backups="backups-done",
            processors="mail-done",
            registerCopies="register-done",
        )
        with self.assertRaises(erasure.Incomplete):
            erasure.close_case(self.db, saved, {"logs": "logs-done"})
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(erasure, "inventory", return_value={"user": 0}),
            patch("firebase_admin.initialize_app"),
            patch("firebase_admin.delete_app"),
            patch("firebase_admin.auth.get_user", side_effect=UserNotFoundError("missing")),
            patch("google.cloud.firestore_admin_v1.FirestoreAdminClient") as admin,
        ):
            client = admin.return_value.__enter__.return_value
            earliest = client.get_database.return_value.earliest_version_time
            earliest.timestamp.return_value = 20
            with self.assertRaisesRegex(erasure.Incomplete, "historical read window"):
                erasure.close_case(self.db, saved, evidence)
            self.assertEqual(self.db.execute("SELECT count(*) FROM cases").fetchone()[0], 1)
            earliest.timestamp.return_value = 30
            erasure.close_case(self.db, saved, evidence)
        self.assertEqual(self.db.execute("SELECT count(*) FROM cases").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT count(*) FROM delivery").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT cutoff FROM projects").fetchone()[0], 25)
        raw = self.path.read_bytes()
        for former_value in (*self.owner.values(), "private-mail-id"):
            self.assertNotIn(former_value.encode(), raw)
