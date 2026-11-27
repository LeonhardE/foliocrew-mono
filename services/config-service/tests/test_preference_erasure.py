import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.erase_preferences import firestore_preferences, main
from app.preferences import SQLitePreferencesStore, preference_keys


class PreferenceErasureTests(unittest.TestCase):
    def test_existing_history_and_malformed_rows_removed_only_for_subject_on_repeated_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "prefs.db"
            store = SQLitePreferencesStore(str(path))
            for uid in ("subject", "control"):
                store.save_language(uid, {"language": "zh-Hant", "expectedVersion": 0})
                store.save_currency(uid, {"defaultPortfolioCurrency": "CAD", "expectedVersion": 0})
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute(
                        "INSERT INTO user_preferences VALUES (?, ?)",
                        (preference_keys(uid)[0], "bad"),
                    )
            control = store.get_unified("control")
            for args, count in (([], 3), (["--apply"], 0), (["--apply"], 0)):
                out = io.StringIO()
                with patch("sys.stdin", io.StringIO("subject\n")), redirect_stdout(out):
                    self.assertEqual(main(["--sqlite", str(path), *args]), 0)
                self.assertEqual(json.loads(out.getvalue())["remaining"], count)
                self.assertNotIn("subject", out.getvalue())
                self.assertEqual(SQLitePreferencesStore(str(path)).get_unified("control"), control)
            self.assertIsNone(store.get_unified("subject")["language"]["preferences"])

    def test_firestore_atomic_batch_then_independent_complete_readback(self):
        client = Mock()
        refs = {k: SimpleNamespace(path=f"user_preferences/{k}") for k in preference_keys("one")}
        client.collection.return_value.document.side_effect = refs.__getitem__
        result = [SimpleNamespace(reference=ref, exists=False) for ref in refs.values()]
        client.get_all.return_value = result[::-1]
        self.assertEqual(firestore_preferences(client, "one", apply=True), 0)
        batch = client.batch.return_value
        self.assertEqual(
            [call.args[0] for call in batch.delete.call_args_list], list(refs.values())
        )
        batch.commit.assert_called_once_with(retry=None, timeout=10)
        for bad in (result[:-1], result + result[:1]):
            client.get_all.return_value = bad
            with self.assertRaises(RuntimeError):
                firestore_preferences(client, "one", apply=False)

    def test_active_or_unverifiable_identity_blocks_firestore_apply(self):
        with (
            patch("app.erase_preferences.require_disabled_account", side_effect=ValueError),
            patch("app.erase_preferences.firestore.Client") as client,
            patch("sys.stdin", io.StringIO("one\n")),
            self.assertRaises(SystemExit) as failure,
        ):
            main(["--project", "test", "--database", "(default)", "--apply"])
        client.assert_not_called()
        self.assertNotEqual(failure.exception.code, 0)
