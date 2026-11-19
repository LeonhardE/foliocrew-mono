"""A User handoff preserves source reads and committed initialization receipts."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_channel_follows import inputs
from test_fx_follows import update

from app.channel_follows import ChannelFollowsUnavailable, SQLiteChannelFollowsStore
from app.resources import ResourceUnavailable, SQLiteUserResourceStore
from app.watchlist import SQLiteWatchlistStore, WatchlistUnavailable

UID = "user-handoff-fixture"


class ListWritePauseTests(unittest.TestCase):
    def test_paused_lists_keep_reads_noops_and_existing_receipts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "user.sqlite3")
            watchlists = SQLiteWatchlistStore(path)
            channels = SQLiteChannelFollowsStore(path)
            resources = SQLiteUserResourceStore(path)
            instrument = {
                "symbol": "AAPL",
                "name": "Synthetic instrument",
                "instrumentType": "stock",
                "currency": "USD",
                "addedAt": "2026-11-19T05:00:00Z",
            }
            existing = watchlists.change(UID, "AAPL", instrument)
            fx = watchlists.save_fx(UID, update())
            follows = channels.replace(UID, 0, inputs("@fixture"))
            receipt = resources.initialize(UID, "watchlist", "original_operation")
            with patch.dict("os.environ", {"USER_LIST_WRITES_PAUSED": "true"}):
                with self.assertRaises(WatchlistUnavailable):
                    watchlists.change(UID, "AAPL", None)
                with self.assertRaises(WatchlistUnavailable):
                    watchlists.save_fx(UID, update(version=fx["version"]))
                with self.assertRaises(ChannelFollowsUnavailable):
                    channels.replace(UID, follows["revision"], [])
                with self.assertRaises(ResourceUnavailable):
                    resources.initialize(UID, "watchlist", "new_operation")
                self.assertEqual(watchlists.get(UID), existing)
                self.assertEqual(watchlists.change(UID, "AAPL", instrument), existing)
                self.assertEqual(watchlists.get_fx(UID), fx)
                self.assertEqual(channels.get(UID), follows)
                self.assertEqual(
                    channels.replace(UID, follows["revision"], inputs("@fixture")), follows
                )
                self.assertEqual(
                    resources.initialize(UID, "watchlist", "original_operation"), receipt
                )
            self.assertEqual(watchlists.change(UID, "AAPL", None), [])
