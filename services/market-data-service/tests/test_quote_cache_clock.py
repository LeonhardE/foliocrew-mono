"""Fractional quote cache clocks with actual SQLite and Firestore SDK serialization."""

import copy
import math
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from google.auth.credentials import AnonymousCredentials
from google.cloud.firestore_v1 import Client, types

from app.cost_controls import CostControls
from app.market_cache import CacheUnavailable, Entry, FirestoreMarketCache, SQLiteMarketCache
from app.market_data import MarketService
from app.valuation_quotes import TTL, QuoteService, cache_key, checked_quote

NOW = datetime(2026, 11, 13, 19, tzinfo=UTC).timestamp()
US = {"symbol": "AAPL", "market": "XNAS", "currency": "USD"}
OTHER = {**US, "symbol": "MSFT"}
META = {
    "symbol": "AAPL",
    "exchangeName": "NMS",
    "instrumentType": "EQUITY",
    "currency": "USD",
    "regularMarketPrice": 123.45,
    "regularMarketTime": int(NOW),
    "exchangeTimezoneName": "America/New_York",
}


class MemoryRPC:
    """Only the last RPC seam is replaced; real SDK writes/read parsers handle values."""

    def __init__(self):
        self.documents = {}
        self.calls = []
        self.before_read = None

    def begin_transaction(self, request, **kwargs):
        self.calls.append("begin")
        return types.BeginTransactionResponse(transaction=b"synthetic-transaction")

    def batch_get_documents(self, request, **kwargs):
        self.calls.append("batch_get")
        if self.before_read and not request.get("transaction"):
            callback, self.before_read = self.before_read, None
            callback()
        for name in request["documents"]:
            if name in self.documents:
                yield types.BatchGetDocumentsResponse(
                    found=types.Document.deserialize(self.documents[name]),
                    read_time=datetime.fromtimestamp(NOW, UTC),
                )
            else:
                yield types.BatchGetDocumentsResponse(
                    missing=name, read_time=datetime.fromtimestamp(NOW, UTC)
                )

    def commit(self, request, **kwargs):
        self.calls.append("commit")
        for write in request["writes"]:
            self.assert_update(write)
            incoming = types.Document.deserialize(types.Document.serialize(write.update))
            fields = list(write.update_mask.field_paths)
            if fields:
                stored = (
                    types.Document.deserialize(self.documents[incoming.name])
                    if incoming.name in self.documents
                    else types.Document(name=incoming.name)
                )
                for field in fields:
                    assert "." not in field
                    stored.fields[field] = incoming.fields[field]
            else:
                stored = incoming
            self.documents[incoming.name] = types.Document.serialize(stored)
        return types.CommitResponse(
            write_results=[
                types.WriteResult(update_time=datetime.fromtimestamp(NOW, UTC))
                for _ in request["writes"]
            ],
            commit_time=datetime.fromtimestamp(NOW, UTC),
        )

    @staticmethod
    def assert_update(write):
        assert write._pb.WhichOneof("operation") == "update"

    def rollback(self, **kwargs):
        self.calls.append("rollback")


class Provider:
    def __init__(self):
        self.calls = []
        self.failed = False

    def fetch(self, symbols, timeout):
        self.calls.append(list(symbols))
        return {
            symbol: {"error": "upstream_unavailable"} if self.failed else {**META, "symbol": symbol}
            for symbol in symbols
        }


class QuoteCacheClockTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def stores(self):
        path = str(Path(self.folder.name) / "market.sqlite3")
        yield "sqlite", lambda: SQLiteMarketCache(path), None
        rpc = MemoryRPC()
        client = Client(project="synthetic-cache-clock", credentials=AnonymousCredentials())
        client._firestore_api_internal = rpc

        def reopen():
            with patch("app.market_cache.firestore.Client", return_value=client):
                return FirestoreMarketCache(
                    "synthetic-cache-clock",
                    controls=CostControls(storage_limit=600, clock=lambda: 0),
                )

        yield "firestore-sdk", reopen, rpc

    def test_fractional_good_price_survives_real_put_read_invalidate_and_restart(self):
        for name, reopen, rpc in self.stores():
            with self.subTest(store=name):
                cache, provider = reopen(), Provider()
                service = QuoteService(
                    MarketService(cache, clock=lambda: NOW + 0.25), provider=provider
                )
                self.assertEqual(
                    service.quotes({"instruments": [US]})["items"][0]["price"], "123.45"
                )
                cache.invalidate(cache_key(US))
                entry = cache.get_many([cache_key(US)])[cache_key(US)]
                self.assertEqual(entry.updated_at, NOW + 0.25)
                self.assertEqual(entry.value["_refreshAfter"], NOW + 0.25 + TTL)
                self.assertIsNone(entry.value["reason"])
                self.assertEqual(entry.value["sourceAsOf"], "2026-11-13T19:00:00Z")
                for current in [cache, reopen()]:
                    view = QuoteService(
                        MarketService(current, clock=lambda: NOW + 0.5), provider=provider
                    )
                    for cached in [True, False]:
                        response = view.quotes({"instruments": [US]}, cached_only=cached)
                        self.assertEqual(response["items"][0]["price"], "123.45")
                self.assertEqual(provider.calls, [["AAPL"]])
                if rpc:
                    self.assertIn("commit", rpc.calls)
                    self.assertIn("batch_get", rpc.calls)

    def test_two_items_merge_only_one_new_upstream_identity_and_read_back_together(self):
        for name, reopen, _rpc in self.stores():
            with self.subTest(store=name):
                provider, cache = Provider(), reopen()
                view = QuoteService(
                    MarketService(cache, clock=lambda: NOW + 0.25), provider=provider
                )
                view.quotes({"instruments": [US]})
                response = view.quotes({"instruments": [US, OTHER]})
                self.assertTrue(all(item["price"] == "123.45" for item in response["items"]))
                restarted = QuoteService(
                    MarketService(reopen(), clock=lambda: NOW + 0.5), provider=provider
                )
                response = restarted.quotes({"instruments": [US, OTHER]})
                self.assertTrue(all(item["price"] == "123.45" for item in response["items"]))
                self.assertEqual(provider.calls, [["AAPL"], ["MSFT"]])

    def test_integer_and_existing_fractional_entries_keep_exact_expiry_bounds(self):
        for updated in [NOW, NOW + 0.25]:
            value = checked_quote(US, META, updated)
            value["_refreshAfter"] = updated + TTL
            entry = Entry(value, updated)
            self.assertIsNotNone(QuoteService.cached(entry, US, updated))
            self.assertEqual(QuoteService.cached(entry, US, updated + TTL)["status"], "stale")
            value["_refreshAfter"] = math.nextafter(updated + TTL, math.inf)
            self.assertIsNone(QuoteService.cached(entry, US, updated))
            value["_refreshAfter"] = math.nextafter(updated, -math.inf)
            self.assertIsNone(QuoteService.cached(entry, US, updated))

    def test_invalid_internal_times_mismatch_and_precise_future_are_rejected(self):
        value = checked_quote(US, META, NOW + 0.25)
        value["_refreshAfter"] = NOW + 0.25 + TTL
        invalid = [None, True, "private", float("nan"), math.inf, -math.inf, 10**1000]
        for updated in invalid + [NOW - 0.01, NOW + 1]:
            self.assertIsNone(
                QuoteService.cached(Entry(copy.deepcopy(value), updated), US, NOW + 0.5)
            )
        self.assertIsNone(
            QuoteService.cached(Entry(copy.deepcopy(value), NOW + 0.25), US, NOW + 0.125)
        )
        short_expiry = {**value, "_refreshAfter": NOW + 300}
        self.assertIsNone(QuoteService.cached(Entry(short_expiry, NOW + 0.25), US, NOW + 0.125))
        for until in invalid:
            bad = {**value, "_refreshAfter": until}
            self.assertIsNone(QuoteService.cached(Entry(bad, NOW + 0.25), US, NOW + 0.5))

    def test_negative_legacy_entries_and_original_seven_day_limit(self):
        updated = NOW + 0.25
        missing = checked_quote(US, {"error": "not_found"}, updated)
        missing["_refreshAfter"] = updated + 300
        self.assertEqual(
            QuoteService.cached(Entry(missing, updated), US, updated)["reason"], "not_found"
        )
        value = checked_quote(US, META, updated)
        value["_refreshAfter"] = updated + TTL
        self.assertIsNotNone(QuoteService.cached(Entry(value, updated), US, NOW + 7 * 86400))
        self.assertIsNone(
            QuoteService.cached(
                Entry(value, updated), US, math.nextafter(NOW + 7 * 86400, math.inf)
            )
        )

    def test_provider_failure_retains_stored_usable_price(self):
        for name, reopen, _rpc in self.stores():
            with self.subTest(store=name):
                cache, provider, clock = reopen(), Provider(), [NOW + 0.25]
                view = QuoteService(
                    MarketService(cache, clock=lambda clock=clock: clock[0]), provider=provider
                )
                view.quotes({"instruments": [US]})
                clock[0] += TTL + 1
                provider.failed = True
                response = view.quotes({"instruments": [US]})
                self.assertEqual(response["items"][0]["price"], "123.45")
                self.assertEqual(response["items"][0]["status"], "stale")
                cache.invalidate(cache_key(US))
                self.assertEqual(
                    cache.get_many([cache_key(US)])[cache_key(US)].value["price"], "123.45"
                )

    def test_concurrent_new_write_is_conservatively_missing_until_next_request(self):
        for name, reopen, _rpc in self.stores():
            with self.subTest(store=name):
                cache, provider = reopen(), Provider()
                value = checked_quote(US, META, NOW + 0.75)
                value["_refreshAfter"] = NOW + 0.75 + TTL
                clock = [NOW + 0.5]
                started = []

                def request_clock(started=started, clock=clock):
                    started.append(clock[0])
                    return clock[0]

                original_read = cache.get_many

                def concurrent_write_then_read(
                    keys, started=started, reopen=reopen, value=value, original_read=original_read
                ):
                    self.assertEqual(started, [NOW + 0.5])
                    reopen().put(cache_key(US), value, NOW + 0.75)
                    return original_read(keys)

                view = QuoteService(MarketService(cache, clock=request_clock), provider=provider)
                with patch.object(
                    cache, "get_many", side_effect=concurrent_write_then_read
                ) as read:
                    response = view.quotes({"instruments": [US]})
                    self.assertEqual(read.call_count, 1)
                self.assertIsNone(response["items"][0]["price"])
                self.assertEqual(provider.calls, [])
                clock[0] = NOW + 0.875
                self.assertEqual(view.quotes({"instruments": [US]})["items"][0]["price"], "123.45")
                self.assertEqual(provider.calls, [])

    def test_firestore_missing_internal_updated_fails_closed_without_repair_or_provider(self):
        _name, reopen, rpc = next(row for row in self.stores() if row[0] == "firestore-sdk")
        cache = reopen()
        value = checked_quote(US, META, NOW + 0.25)
        value["_refreshAfter"] = NOW + 0.25 + TTL
        cache.put(cache_key(US), value, NOW + 0.25)
        name = cache.document(cache_key(US))._document_path
        doc = types.Document.deserialize(rpc.documents[name])
        del doc.fields["updated"]
        rpc.documents[name] = types.Document.serialize(doc)
        fresh = reopen()
        before = dict(rpc.documents)
        with self.assertRaises(CacheUnavailable):
            fresh.get_many([cache_key(US)])
        provider = Provider()
        view = QuoteService(MarketService(fresh, clock=lambda: NOW + 0.5), provider=provider)
        self.assertIsNone(view.quotes({"instruments": [US]})["items"][0]["price"])
        self.assertEqual(provider.calls, [])
        self.assertEqual(rpc.documents, before)
