"""Real pinned yfinance formatting and provider subprocesses, with all network denied."""

import json
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from app.valuation_quotes import YahooQuoteProvider, checked_quote

NOW = datetime(2026, 11, 13, 23, tzinfo=UTC).timestamp()
OBSERVED = int(NOW - 3600)

SITE = """
import json, socket
def no_network(*args, **kwargs):
    raise AssertionError("Synthetic fixture forbids network")
socket.socket.connect = no_network
socket.create_connection = no_network
socket.getaddrinfo = no_network
import curl_cffi.requests
curl_cffi.requests.Session.request = no_network
import pandas as pd
import yfinance as yf
from yfinance.scrapers.history import PriceHistory
native_metadata = yf.Ticker.get_history_metadata
rows = json.loads(ROWS_JSON)
class OfflineTicker:
    get_history_metadata = native_metadata
    def __init__(self, symbol):
        self.symbol = symbol
        self.p = object.__new__(PriceHistory)
        self.p._history_metadata = None
        self.p._history_metadata_formatted = False
        self.p._history_metadata_lazy = None
    def history(self, **kwargs):
        assert kwargs == dict(period="5d", interval="1d", auto_adjust=False,
                              actions=False, timeout=2, raise_errors=True, repair=False)
        row = rows[self.symbol]
        observed = row["observed"]
        if row.get("timestamp"):
            observed = pd.Timestamp(observed)
        self.p._history_metadata = dict(symbol=self.symbol, exchangeName="NMS",
            instrumentType="EQUITY", currency="USD", regularMarketPrice=123.45,
            regularMarketTime=observed, exchangeTimezoneName=row.get("zone", "America/New_York"))
    def _lazy_load_price_history(self):
        return self.p
yf.Ticker = OfflineTicker
"""


def worker(rows):
    with tempfile.TemporaryDirectory() as folder:
        source = SITE.replace("ROWS_JSON", repr(json.dumps(rows)))
        (Path(folder) / "sitecustomize.py").write_text(source)
        previous = os.environ.get("PYTHONPATH", "")
        with patch.dict(os.environ, {"PYTHONPATH": folder + os.pathsep + previous}):
            return YahooQuoteProvider().fetch(list(rows), 5)


class QuoteMetadataTimestampTests(unittest.TestCase):
    def test_real_pinned_formatter_survives_actual_worker_json_and_keeps_utc_seconds(self):
        first_fold = int(datetime(2026, 11, 1, 5, 30, tzinfo=UTC).timestamp())
        second_fold = int(datetime(2026, 11, 1, 6, 30, tzinfo=UTC).timestamp())
        rows = {
            "AAPL": {"observed": OBSERVED},
            "TOKYO": {"observed": OBSERVED, "zone": "Asia/Tokyo"},
            "FIRST": {"observed": first_fold},
            "SECOND": {"observed": second_fold},
        }
        values = worker(rows)
        self.assertEqual(set(values), set(rows))
        for symbol, row in rows.items():
            self.assertIs(type(values[symbol]["regularMarketTime"]), int)
            self.assertEqual(values[symbol]["regularMarketTime"], row["observed"])
        value = checked_quote(
            {"symbol": "AAPL", "market": "XNAS", "currency": "USD"}, values["AAPL"], NOW
        )
        self.assertEqual(value["price"], "123.45")
        self.assertEqual(value["sourceAsOf"], "2026-11-13T22:00:00Z")
        self.assertEqual(value["reason"], None)

    def test_naive_and_fractional_datetimes_do_not_guess_zones_or_round_observations(self):
        rows = {
            "NAIVE": {"observed": "2026-11-13T22:00:00", "timestamp": True},
            "MICRO": {"observed": "2026-11-13T22:00:00.000001Z", "timestamp": True},
            "NANO": {"observed": "2026-11-13T22:00:00.000000001Z", "timestamp": True},
        }
        values = worker(rows)
        self.assertEqual(set(values), set(rows))
        for symbol in rows:
            value = checked_quote(
                {"symbol": symbol, "market": "XNAS", "currency": "USD"}, values[symbol], NOW
            )
            self.assertIsNone(value["price"])
            self.assertEqual(value["reason"], "unknown_time")

    def test_original_future_and_expired_time_checks_still_reject_normalized_observations(self):
        rows = {
            "FUTURE": {"observed": int(NOW + 1)},
            "EXPIRED": {"observed": int(NOW - 7 * 86400 - 1)},
        }
        values = worker(rows)
        self.assertEqual(set(values), set(rows))
        for symbol, reason in [("FUTURE", "unknown_time"), ("EXPIRED", "not_found")]:
            value = checked_quote(
                {"symbol": symbol, "market": "XNAS", "currency": "USD"}, values[symbol], NOW
            )
            self.assertIsNone(value["price"])
            self.assertEqual(value["reason"], reason)
