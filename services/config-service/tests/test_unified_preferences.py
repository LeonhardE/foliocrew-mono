"""Unified account read keeps three independent preference fences."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.preferences import (
    FirestorePreferencesStore,
    PreferencesUnavailable,
    SQLitePreferencesStore,
    currency_owner,
    get_preferences_store,
    language_owner,
)
from folioview_shared.auth import CurrentUser, require_google_user
from folioview_shared.identity import owner_key

UID = "owner-preference-batch"
UI = {"theme": "system", "language": "zh", "defaultChartRange": "1y"}
KEYS = (owner_key(UID), language_owner(UID), currency_owner(UID))


class UnifiedSQLiteTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = str(Path(directory.name) / "preferences.sqlite3")
        self.store = SQLitePreferencesStore(self.path)

    def test_one_query_preserves_original_versions_and_explicit_system_theme(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "INSERT INTO user_preferences VALUES (?, ?)",
                (KEYS[0], json.dumps({"version": 1, "preferences": UI})),
            )
        for version in range(3):
            self.store.save_language(UID, {"language": "zh-Hant", "expectedVersion": version})
        for version in range(2):
            self.store.save_currency(
                UID, {"defaultPortfolioCurrency": "CAD", "expectedVersion": version}
            )
        traced = []
        connect = self.store.connection

        @contextmanager
        def traced_connection():
            with connect() as db:
                db.set_trace_callback(traced.append)
                yield db

        with patch.object(self.store, "connection", traced_connection):
            snapshot = self.store.get_unified(UID)
        self.assertEqual(len([line for line in traced if line.startswith("SELECT")]), 1)
        self.assertEqual(snapshot["ui"], {"state": "available", "preferences": UI, "version": 1})
        self.assertEqual(snapshot["language"]["version"], 3)
        self.assertEqual(snapshot["currency"]["version"], 2)
        self.assertEqual(snapshot["currency"]["currencyGeneration"], 1)
        self.assertEqual(
            snapshot["effective"],
            {
                "theme": "system",
                "language": "zh-Hant",
                "defaultPortfolioCurrency": "CAD",
                "defaultChartRange": "1y",
            },
        )
        other = self.store.get_unified("different-owner")
        for section in ("ui", "language", "currency"):
            self.assertEqual(other[section]["version"], 0)
            self.assertIsNone(other[section]["preferences"])
        self.assertEqual(other["currency"]["currencyGeneration"], 0)
        self.assertEqual(
            other["effective"],
            {
                "theme": "light",
                "language": "en",
                "defaultPortfolioCurrency": "USD",
                "defaultChartRange": "1m",
            },
        )

    def test_corrupt_record_is_distinct_from_absence_and_keeps_other_parts_available(self):
        self.store.save(UID, UI, 0)
        self.assertEqual(self.store.get_unified(UID)["effective"]["language"], "zh")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executemany(
                "INSERT INTO user_preferences VALUES (?, ?)",
                [(KEYS[1], "null"), (KEYS[2], "{broken")],
            )
        snapshot = self.store.get_unified(UID)
        self.assertEqual(snapshot["language"], {"state": "unavailable"})
        self.assertEqual(snapshot["currency"], {"state": "unavailable"})
        self.assertEqual(snapshot["ui"]["preferences"], UI)
        self.assertEqual(snapshot["effective"]["theme"], "system")
        self.assertIsNone(snapshot["effective"]["language"])
        self.assertIsNone(snapshot["effective"]["defaultPortfolioCurrency"])

    def test_owner_route_is_private_and_total_storage_failure_returns_503(self):
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/v2/preferences").status_code, 401)
            with patch.dict(
                app.dependency_overrides,
                {
                    require_google_user: lambda: CurrentUser(
                        uid=UID, email=None, displayName=None, photoURL=None
                    ),
                    get_preferences_store: lambda: self.store,
                },
            ):
                response = client.get("/api/v2/preferences", params={"owner": "foreign"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(response.json(), self.store.get_unified(UID))
                with patch.object(self.store, "get_unified", side_effect=PreferencesUnavailable):
                    unavailable = client.get("/api/v2/preferences")
                self.assertEqual(unavailable.status_code, 503)
                self.assertEqual(unavailable.headers["cache-control"], "no-store")


class UnifiedFirestoreTests(unittest.TestCase):
    def setUp(self):
        self.store = FirestorePreferencesStore.__new__(FirestorePreferencesStore)
        self.store.client = Mock()
        self.store.collection = Mock()
        self.refs = {
            key: SimpleNamespace(
                _document_path=f"projects/project/databases/config/documents/user_preferences/{key}"
            )
            for key in KEYS
        }
        self.store.collection.document.side_effect = self.refs.__getitem__

    def row(self, key, value, *, exists=True):
        return SimpleNamespace(reference=self.refs[key], exists=exists, to_dict=lambda: value)

    def test_single_batch_maps_out_of_order_snapshots_and_checks_document_presence(self):
        rows = [
            self.row(KEYS[2], {}, exists=False),
            self.row(KEYS[1], None),
            self.row(KEYS[0], {"version": 1, "preferences": UI, "revision": 17}),
        ]
        self.store.client.get_all.return_value = iter(rows)
        actual = self.store.get_unified(UID)
        self.store.client.get_all.assert_called_once_with(
            list(self.refs.values()), timeout=4, retry=None
        )
        self.assertEqual(actual["ui"]["version"], 17)
        self.assertEqual(actual["language"], {"state": "unavailable"})
        self.assertEqual(actual["currency"]["version"], 0)

    def test_incomplete_duplicate_or_interrupted_batch_cannot_be_used_as_absence(self):
        missing = [self.row(key, None, exists=False) for key in KEYS]

        def interrupted():
            yield missing[0]
            raise TimeoutError

        for stream in (missing[:-1], [*missing, missing[0]], interrupted()):
            self.store.client.get_all.return_value = iter(stream)
            with self.assertRaises(PreferencesUnavailable):
                self.store.get_unified(UID)
