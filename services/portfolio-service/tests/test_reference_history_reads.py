"""Reader rollout floor for lossless public-history storage; synthetic data only."""

import copy
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from fixtures import SOURCE, UID, HoldingsFixture
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from test_firestore_store import MemoryRpc

from app.holdings import PortfolioService
from app.store import (
    FirestorePortfolioStore,
    SQLitePortfolioStore,
    StoreUnavailable,
    document_path,
)
from folioview_shared.encrypted.authority import RegistryCertificateMemo
from folioview_shared.encrypted.constants import MAX_READ_BYTES, MAX_STORED_DOCUMENT_BYTES
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json, strict_json_loads
from folioview_shared.encrypted.reference_history import (
    decode_reference_history,
    encode_reference_history,
)
from folioview_shared.identity import owner_key


class ReferenceHistoryReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = HoldingsFixture()
        fixture.certificates = {
            key: value for key, value in fixture.certificates.items() if not key.startswith("A")
        }
        history, known, previous = [], {}, None
        memo = RegistryCertificateMemo()
        for generation in range(25):
            if generation:
                principal = f"synthetic_{generation}"
                for role in ("agent_sig", "agent_enc"):
                    fixture.add_key(
                        f"{principal}_{role}", role, principal, f"connection_{generation}"
                    )
            bundle = fixture.make_bundle(previous=previous)
            for entry in bundle["entries"]:
                certificate = entry["certificate"]
                known.setdefault(certificate["payload"], certificate)
                entry["certificate"] = copy.deepcopy(known[certificate["payload"]])
            previous = fixture.verify(bundle, previous=previous, signature_memo=memo)
            history.append(bundle)
        cls.fixture, cls.history = fixture, history
        fixture.bundle, fixture.registry = history[-1], previous
        cls.row = {
            "version": 1,
            "ownerSubject": owner_key(UID),
            "sourceId": SOURCE,
            "vaultId": fixture.vault,
            "rootJwk": fixture.root_public,
            "rootKeyId": fixture.root_id,
            "registryHistory": history,
            "resourceRef": fixture.resource,
            "sourceEpoch": 1,
            "active": True,
            "writerKeyIds": [fixture.kid("device_sig")],
            "recipientKeyIds": sorted([fixture.kid("device_enc"), fixture.kid("recovery_enc")]),
        }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sqlite = SQLitePortfolioStore(str(Path(self.temp.name) / "portfolio.sqlite"))
        self.client = firestore.Client(
            project="synthetic-portfolio", database="portfolio", credentials=AnonymousCredentials()
        )
        self.rpc = MemoryRpc(self.client)
        self.client._firestore_api_internal = self.rpc
        self.cloud = FirestorePortfolioStore("synthetic-portfolio", "portfolio", client=self.client)
        self.path = document_path("portfolio_authorities", owner_key(UID), SOURCE)
        self.name = self.client.document(self.path)._document_path

    def seed(self, store, row, *, reference=True):
        physical = copy.deepcopy(row)
        if reference:
            physical["registryHistory"] = encode_reference_history(physical["registryHistory"])
        if store is self.cloud:
            physical["registryHistory"] = canonical_json(physical["registryHistory"])
            self.rpc.documents[self.name] = physical
        else:
            with closing(self.sqlite.connect()) as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO portfolio_documents(path, body) VALUES (?, ?)",
                    (self.path, canonical_json(physical).decode()),
                )
        return copy.deepcopy(physical)

    def physical(self, store):
        if store is self.cloud:
            return copy.deepcopy(self.rpc.documents[self.name])
        with closing(self.sqlite.connect()) as connection:
            body = connection.execute(
                "SELECT body FROM portfolio_documents WHERE path = ?", (self.path,)
            ).fetchone()[0]
        return strict_json_loads(body, max_bytes=MAX_STORED_DOCUMENT_BYTES)

    def test_large_reference_reads_restore_complete_authority_without_writes(self):
        self.assertGreater(len(canonical_json(self.row)), MAX_STORED_DOCUMENT_BYTES)
        self.assertLess(len(canonical_json(self.row)), MAX_READ_BYTES)
        expected = canonical_json(self.row)
        for store in (self.sqlite, self.cloud):
            with self.subTest(store=type(store).__name__):
                physical = self.seed(store, self.row)
                single = store.transact(lambda unit: unit.get(self.path))
                batch = store.transact(lambda unit: unit.get_many([self.path]))[self.path]
                self.assertEqual(expected, canonical_json(single))
                self.assertEqual(expected, canonical_json(batch))
                service = PortfolioService(store, clock=lambda: 1000)
                self.assertEqual(service.metadata(UID, SOURCE)["state"], "active")
                self.assertEqual(service.metadata_many(UID, [SOURCE])[0]["sourceId"], SOURCE)
                self.assertEqual(self.physical(store), physical)
                if store is self.cloud:
                    self.assertFalse(
                        any(
                            kind == "commit" and kwargs["request"]["writes"]
                            for kind, kwargs in self.rpc.calls
                        )
                    )

    def test_legacy_reads_and_reference_writes_preserve_complete_histories(self):
        row = {**self.row, "registryHistory": self.history[:1]}
        for store in (self.sqlite, self.cloud):
            with self.subTest(store=type(store).__name__):
                original = self.seed(store, row, reference=False)
                self.assertEqual(store.transact(lambda unit: unit.get(self.path)), row)
                self.assertEqual(self.physical(store), original)
                store.transact(lambda unit: unit.put(self.path, row))
                physical = self.physical(store)
                history = physical["registryHistory"]
                if type(history) is bytes:
                    history = strict_json_loads(history)
                self.assertIs(type(history), dict)
                self.assertEqual(decode_reference_history(history), row["registryHistory"])
                store.transact(lambda unit: unit.put(self.path, self.row))
                self.assertEqual(store.transact(lambda unit: unit.get(self.path)), self.row)
                physical = self.physical(store)
                history = physical["registryHistory"]
                if type(history) is bytes:
                    history = strict_json_loads(history)
                self.assertIs(type(history), dict)
                self.assertEqual(decode_reference_history(history), self.row["registryHistory"])

    def test_large_authority_remains_usable_for_snapshot_and_fence_writes(self):
        for store in (self.sqlite, self.cloud):
            with self.subTest(store=type(store).__name__):
                # Exercise the ordinary verified service operations, not an
                # enrollment shortcut or a direct trusted-state install.
                store.transact(lambda unit: unit.put(self.path, self.row))
                service = PortfolioService(store, clock=lambda: 1000)
                if store is self.cloud:
                    self.rpc.aborts = 1
                receipt = self.fixture.write(service)
                self.assertEqual(service.snapshot(UID, SOURCE)["receipt"], receipt)
                self.assertEqual(service.metadata(UID, SOURCE)["state"], "active")
                mutation = self.fixture.mutate(service)
                self.assertEqual(mutation["state"], "pending")
                metadata = service.metadata(UID, SOURCE)
                self.assertEqual(metadata["sourceEpoch"], 2)
                self.assertEqual(metadata["state"], "revoking")
                restored = store.transact(lambda unit: unit.get(self.path))
                self.assertEqual(restored["registryHistory"], self.history)

    def test_reference_writes_reject_compact_input_and_expanded_overflow_atomically(self):
        for store in (self.sqlite, self.cloud):
            with self.subTest(store=type(store).__name__):
                store.transact(lambda unit: unit.put(self.path, self.row))
                before = self.physical(store)
                compact_input = {
                    **self.row,
                    "registryHistory": encode_reference_history(self.history),
                }
                oversized = {**self.row, "padding": "x" * MAX_READ_BYTES}
                for candidate, code in (
                    (compact_input, "malformed_request"),
                    (oversized, "payload_too_large"),
                ):
                    with self.assertRaises(ContractError) as raised:
                        store.transact(
                            lambda unit, candidate=candidate: unit.put(self.path, candidate)
                        )
                    self.assertEqual(raised.exception.code, code)
                    self.assertEqual(self.physical(store), before)

    def test_corrupt_references_fail_single_and_batch_reads_without_rewrite(self):
        for store in (self.sqlite, self.cloud):
            with self.subTest(store=type(store).__name__):
                self.seed(store, self.row)
                physical = self.physical(store)
                compact = physical["registryHistory"]
                if type(compact) is bytes:
                    compact = strict_json_loads(compact)
                compact["bundles"][-1]["entries"][0][0] = 9999
                if store is self.cloud:
                    self.rpc.documents[self.name]["registryHistory"] = canonical_json(compact)
                else:
                    physical["registryHistory"] = compact
                    with closing(self.sqlite.connect()) as connection:
                        connection.execute(
                            "UPDATE portfolio_documents SET body = ? WHERE path = ?",
                            (canonical_json(physical).decode(), self.path),
                        )
                before = self.physical(store)
                for many in (False, True):
                    with self.assertRaises(StoreUnavailable):
                        store.transact(
                            lambda unit, many=many: (
                                unit.get_many([self.path]) if many else unit.get(self.path)
                            )
                        )
                self.assertEqual(before, self.physical(store))

    def test_integral_float_references_are_not_normalized_before_validation(self):
        for store in (self.sqlite, self.cloud):
            for number in (0.0, -0.0, 1.0):
                with self.subTest(store=type(store).__name__, number=repr(number)):
                    physical = {
                        **self.row,
                        "registryHistory": encode_reference_history(self.history),
                    }
                    physical["registryHistory"]["bundles"][0]["entries"][0][0] = number
                    if store is self.cloud:
                        # Native Firestore maps must retain numeric types until
                        # the codec checks the original reference, not its JCS.
                        self.rpc.documents[self.name] = copy.deepcopy(physical)
                    else:
                        # Read an existing raw SQLite JSON row without first
                        # using JCS, which would itself turn 0.0 into integer0.
                        with closing(self.sqlite.connect()) as connection:
                            connection.execute(
                                "INSERT OR REPLACE INTO portfolio_documents(path, body) "
                                "VALUES (?, ?)",
                                (self.path, json.dumps(physical, separators=(",", ":"))),
                            )
                    for many in (False, True):
                        with self.assertRaises(StoreUnavailable):
                            store.transact(
                                lambda unit, many=many: (
                                    unit.get_many([self.path]) if many else unit.get(self.path)
                                )
                            )
                    if store is self.cloud:
                        self.assertEqual(self.rpc.documents[self.name], physical)
                    else:
                        with closing(self.sqlite.connect()) as connection:
                            raw = connection.execute(
                                "SELECT body FROM portfolio_documents WHERE path = ?", (self.path,)
                            ).fetchone()[0]
                        self.assertIs(
                            type(json.loads(raw)["registryHistory"]["bundles"][0]["entries"][0][0]),
                            float,
                        )

    def test_original_signature_root_and_current_time_checks_still_reject(self):
        wrong_root = HoldingsFixture()
        bad_signature = copy.deepcopy(self.row)
        bad_signature["registryHistory"][-1]["checkpoint"]["signature"] = "A" * 86
        wrong_binding = {
            **self.row,
            "rootJwk": wrong_root.root_public,
            "rootKeyId": wrong_root.root_id,
        }
        for store in (self.sqlite, self.cloud):
            for row, now in ((bad_signature, 1000), (wrong_binding, 1000), (self.row, 499)):
                with self.subTest(store=type(store).__name__, now=now):
                    before = self.seed(store, row)
                    service = PortfolioService(store, clock=lambda now=now: now)
                    with self.assertRaises(StoreUnavailable):
                        service.metadata(UID, SOURCE)
                    self.assertEqual(before, self.physical(store))

    def test_entire_expanded_row_budget_includes_nonhistory_fields(self):
        # Storage-only padding is not a valid authority schema. It proves that
        # the reader budgets the whole row before any caller could use it.
        row = {**self.row, "padding": ""}
        row["padding"] = "x" * (MAX_READ_BYTES - len(canonical_json(row)))
        self.assertEqual(len(canonical_json(row)), MAX_READ_BYTES)
        for store in (self.sqlite, self.cloud):
            with self.subTest(store=type(store).__name__):
                before = self.seed(store, row)
                self.assertEqual(store.transact(lambda unit: unit.get(self.path)), row)
                self.assertEqual(self.physical(store), before)
                oversized = {**row, "padding": row["padding"] + "x"}
                before = self.seed(store, oversized)
                for many in (False, True):
                    with self.assertRaises(StoreUnavailable):
                        store.transact(
                            lambda unit, many=many: (
                                unit.get_many([self.path]) if many else unit.get(self.path)
                            )
                        )
                self.assertEqual(self.physical(store), before)

    def test_legacy_integer_fields_retain_types_until_authority_validation(self):
        for store in (self.sqlite, self.cloud):
            for field in ("version", "sourceEpoch"):
                with self.subTest(store=type(store).__name__, field=field):
                    row = {**self.row, "registryHistory": self.history[:1], field: 1.0}
                    if store is self.cloud:
                        physical = {
                            **row,
                            "registryHistory": canonical_json(row["registryHistory"]),
                        }
                        self.rpc.documents[self.name] = copy.deepcopy(physical)
                    else:
                        with closing(self.sqlite.connect()) as connection:
                            connection.execute(
                                "INSERT OR REPLACE INTO portfolio_documents(path, body) "
                                "VALUES (?, ?)",
                                (self.path, json.dumps(row, separators=(",", ":"))),
                            )
                    single = store.transact(lambda unit: unit.get(self.path))
                    batch = store.transact(lambda unit: unit.get_many([self.path]))[self.path]
                    self.assertIs(type(single[field]), float)
                    self.assertIs(type(batch[field]), float)
                    service = PortfolioService(store, clock=lambda: 1000)
                    with self.assertRaises(StoreUnavailable):
                        service.metadata(UID, SOURCE)


if __name__ == "__main__":
    unittest.main()
