"""Explicit storage.v2 reader floor; writers and public DTO budgets stay v1."""

import copy
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fixtures import UID, VaultFixture
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from google.cloud.firestore_v1._helpers import encode_dict
from google.cloud.firestore_v1.types import Document, RunQueryResponse
from test_firestore_store import MemoryRpc

from app.store import FirestoreHubStore, SQLiteHubStore, StoreUnavailable, document_path
from app.vaults import VaultService, _current
from folioview_shared.encrypted.authority import RegistryCertificateMemo
from folioview_shared.encrypted.constants import MAX_READ_BYTES, MAX_STORED_DOCUMENT_BYTES
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json
from folioview_shared.encrypted.reference_history import REFERENCE_HISTORY_FORMAT
from folioview_shared.encrypted.reference_history_v2 import (
    MAX_EXPANDED_HISTORY_BYTES,
    TRANSPORT_HISTORY_FORMAT,
    decode_storage_history_v2,
    encode_storage_history_v2,
)


class ReferenceHistoryV2ReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = f = VaultFixture()
        for index in range(22):
            for suffix, role in (("sig", "agent_sig"), ("enc", "agent_enc")):
                f.add_key(f"v2_{index}_{suffix}", role, f"agent_{index}", f"conn_{index}")
        history, known, previous = [], {}, None
        memo = RegistryCertificateMemo()
        for index in range(32):
            bundle = f.make_bundle(previous=previous, revoked=("v2_0_sig",) if index == 31 else ())
            for entry in bundle["entries"]:
                signed = entry["certificate"]
                known.setdefault(signed["payload"], signed)
                entry["certificate"] = copy.deepcopy(known[signed["payload"]])
            previous = f.verify(bundle, previous=previous, signature_memo=memo)
            history.append(bundle)
        cls.history, cls.registry = history, previous
        cls.row = {
            "ownerSubject": f.owner,
            "vaultId": f.vault,
            "rootJwk": f.root_public,
            "rootKeyId": f.root_id,
            "registryHistory": history,
            "archive": f.bootstrap()["archive"],
            "version": len(history),
            "sources": [],
            "operationCount": len(history),
        }
        cls.compact = encode_storage_history_v2(history)
        assert MAX_READ_BYTES < len(canonical_json(history)) < MAX_EXPANDED_HISTORY_BYTES

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.sqlite = SQLiteHubStore(Path(directory.name) / "hub.sqlite3")
        self.client = firestore.Client(
            project="synthetic-hub", database="agent-hub", credentials=AnonymousCredentials()
        )
        self.addCleanup(self.client.close)
        self.rpc = MemoryRpc(self.client)
        self.client._firestore_api_internal = self.rpc
        self.firestore = FirestoreHubStore("synthetic-hub", "agent-hub", client=self.client)
        self.stores = (self.sqlite, self.firestore)

        def query(**kwargs):
            self.rpc.record("query", kwargs)
            return iter(
                RunQueryResponse(document=Document(name=name, fields=encode_dict(value)))
                for name, value in sorted(self.rpc.documents.items())
            )

        self.rpc.run_query = query

    def seed(self, store, path, value):
        if store is self.sqlite:
            with closing(store.connect()) as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO hub_documents(path,body) VALUES(?,?)",
                    (path, json.dumps(value)),
                )
        else:
            self.rpc.documents[self.client.document(path)._document_path] = copy.deepcopy(value)

    def snapshot(self, store):
        if store is self.sqlite:
            with closing(store.connect()) as connection:
                return connection.execute(
                    "SELECT path,body FROM hub_documents ORDER BY path"
                ).fetchall()
        return copy.deepcopy(self.rpc.documents)

    def encoded(self, store, row=None, *, as_bytes=True):
        row = self.row if row is None else row
        compact = encode_storage_history_v2(row["registryHistory"])
        return row | {
            "registryHistory": (
                canonical_json(compact) if store is self.firestore and as_bytes else compact
            )
        }

    def read_all(self, unit, path):
        single = unit.get(path)
        batch = unit.get_many([path])[path]
        scan = dict(unit.scan_owner("hub_persistent_runs", "ownerUid", UID))[path]
        return single, batch, scan

    def test_31_32_generation_vault_reads_restore_authority_without_wire_or_write_activation(self):
        path = document_path("hub_vaults", self.f.owner)
        for count in (31, 32):
            row = self.row | {
                "registryHistory": self.history[:count],
                "version": count,
                "operationCount": count,
            }
            for store in self.stores:
                for as_bytes in (False, True) if store is self.firestore else (False,):
                    with self.subTest(count=count, backend=type(store).__name__, as_bytes=as_bytes):
                        self.seed(store, path, self.encoded(store, row, as_bytes=as_bytes))
                        before = self.snapshot(store)
                        actual, registry = store.transact(
                            lambda unit: _current(unit, self.f.owner, 1000, self.f.vault)
                        )
                        self.assertEqual(row, actual)
                        self.assertEqual(count, registry.registry_sequence)
                        with self.assertRaises(ContractError) as failed:
                            VaultService(store, clock=lambda: 1000).current(UID)
                        self.assertEqual("payload_too_large", failed.exception.code)
                        with self.assertRaises(ContractError):
                            store.transact(lambda unit, actual=actual: unit.put(path, actual))
                        self.assertEqual(before, self.snapshot(store))
        with self.assertRaises(ContractError):
            self.registry.cert(self.f.kid("v2_0_sig"), now=1000)
        self.assertFalse(
            any(kind == "commit" and kwargs["request"]["writes"] for kind, kwargs in self.rpc.calls)
        )

    def test_run_single_batch_scan_and_cache_preserve_large_nonhistory_and_isolation(self):
        path = document_path("hub_persistent_runs", "v2-run")
        # This existing envelope allowance must not be replaced by a 64 KiB cap.
        row = {
            "ownerUid": UID,
            "registryHistory": self.history,
            "manifestJson": "x" * 200000,
            "version": 1.0,
            "sourceEpoch": -0.0,
        }
        for store in self.stores:
            with self.subTest(backend=type(store).__name__):
                self.seed(store, path, self.encoded(store, row))
                before = self.snapshot(store)

                def read(unit):
                    values = self.read_all(unit, path)
                    self.assertEqual((row, row, row), values)
                    self.assertTrue(all(type(value["version"]) is float for value in values))
                    self.assertTrue(all(type(value["sourceEpoch"]) is float for value in values))
                    values[0]["registryHistory"][0]["entries"][0]["active"] = False
                    self.assertEqual(row, unit.get_many([path])[path])
                    self.assertIsNot(
                        values[1]["registryHistory"][0]["entries"][0]["certificate"],
                        values[1]["registryHistory"][1]["entries"][0]["certificate"],
                    )

                store.transact(read)
                self.assertEqual(before, self.snapshot(store))

    def test_v1_relabel_unknown_and_transport_never_receive_the_v2_budget(self):
        for collection in ("hub_vaults", "hub_persistent_runs"):
            path = document_path(collection, "not-v2")
            for profile in (REFERENCE_HISTORY_FORMAT, TRANSPORT_HISTORY_FORMAT, "unknown"):
                for store in self.stores:
                    with self.subTest(
                        collection=collection, profile=profile, backend=type(store).__name__
                    ):
                        compact = self.compact | {"format": profile}
                        history = canonical_json(compact) if store is self.firestore else compact
                        self.seed(store, path, {"ownerUid": UID, "registryHistory": history})
                        with self.assertRaises(StoreUnavailable):
                            store.transact(lambda unit, path=path: unit.get_many([path]))

    def test_original_vault_row_budget_still_deducts_nonhistory_for_v1(self):
        path = document_path("hub_vaults", "legacy-row-ceiling")
        history = self.history[:14]
        compact = encode_storage_history_v2(history) | {"format": REFERENCE_HISTORY_FORMAT}
        row = {"registryHistory": compact, "opaque": "x" * 300000}
        self.assertLess(len(canonical_json(history)), MAX_READ_BYTES)
        self.assertGreater(len(canonical_json(row | {"registryHistory": history})), MAX_READ_BYTES)
        for store in self.stores:
            stored = row | {
                "registryHistory": canonical_json(compact) if store is self.firestore else compact
            }
            self.seed(store, path, stored)
            with self.assertRaises(StoreUnavailable):
                store.transact(lambda unit: unit.get(path))
            # Identical physical/logical content opts in only through storage.v2.
            self.seed(store, path, self.encoded(store, row | {"registryHistory": history}))
            self.assertEqual(
                row | {"registryHistory": history}, store.transact(lambda unit: unit.get(path))
            )

    def test_invalid_native_refs_fail_all_paths_without_numeric_normalization(self):
        path = document_path("hub_persistent_runs", "native-ref-types")
        for reference in (0.0, -0.0, True, -1, 2048):
            for store in self.stores:
                with self.subTest(reference=repr(reference), backend=type(store).__name__):
                    compact = copy.deepcopy(self.compact)
                    compact["bundles"][0]["entries"][0][0] = reference
                    self.seed(store, path, {"ownerUid": UID, "registryHistory": compact})
                    for operation in ("single", "batch", "scan"):

                        def read(unit, operation=operation):
                            if operation == "single":
                                return unit.get(path)
                            if operation == "batch":
                                return unit.get_many([path])
                            return unit.scan_owner("hub_persistent_runs", "ownerUid", UID)

                        with self.subTest(operation=operation), self.assertRaises(StoreUnavailable):
                            store.transact(read)

    def test_native_row_numbers_remain_typed_for_original_authority(self):
        path = document_path("hub_vaults", self.f.owner)
        for field in ("version", "operationCount", "sourceEpoch"):
            for store in self.stores:
                row = self.encoded(store)
                if field == "sourceEpoch":
                    row["sources"] = [
                        {
                            "resourceRef": {
                                "kind": "holdings",
                                "sourceService": "portfolio",
                                "resourceId": "source_A",
                                "incarnation": "incarnation_A",
                            },
                            "sourceEpoch": 1.0,
                        }
                    ]
                    row["version"] += 1
                    row["operationCount"] += 1
                else:
                    row[field] = float(row[field])
                self.seed(store, path, row)
                with self.subTest(field=field, backend=type(store).__name__):
                    actual = store.transact(lambda unit: unit.get_many([path])[path])
                    self.assertIs(
                        type(
                            actual["sources"][0][field] if field == "sourceEpoch" else actual[field]
                        ),
                        float,
                    )
                    with self.assertRaises((ContractError, StoreUnavailable)):
                        store.transact(lambda unit: _current(unit, self.f.owner, 1000))

    def test_corrupt_batch_never_publishes_partial_cache_and_recovery_reloads(self):
        good = document_path("hub_persistent_runs", "good")
        bad = document_path("hub_persistent_runs", "bad")
        row = {"ownerUid": UID, "registryHistory": self.history}
        self.seed(self.firestore, good, self.encoded(self.firestore, row))
        compact = copy.deepcopy(self.compact)
        compact["bundles"][-1]["entries"][-1][0] = 2048
        self.seed(self.firestore, bad, row | {"registryHistory": canonical_json(compact)})

        def read(unit):
            with self.assertRaises(StoreUnavailable):
                unit.get_many([good, bad])
            self.assertEqual({}, unit._reads)
            self.seed(self.firestore, bad, self.encoded(self.firestore, row))
            self.assertEqual({good: row, bad: row}, unit.get_many([good, bad]))

        self.firestore.transact(read)

    def test_expanded_cache_limit_is_not_the_compact_document_size(self):
        paths = [document_path("hub_persistent_runs", f"cache_{index}") for index in range(6)]
        row = {"ownerUid": UID, "registryHistory": self.history}
        size = len(canonical_json(row))
        self.assertGreater(6 * size, 8 * 1024 * 1024)
        for path in paths:
            self.seed(self.firestore, path, self.encoded(self.firestore, row))

        def read(unit):
            values = unit.get_many(paths)
            self.assertEqual({path: row for path in paths}, values)
            count = (8 * 1024 * 1024) // size
            self.assertEqual(count, len(unit._reads))
            self.assertEqual(count * size, unit._read_bytes)
            missing = paths[-1]
            self.assertNotIn((missing, None), unit._reads)
            self.assertEqual(row, unit.get(missing))
            self.assertNotIn((missing, None), unit._reads)

        self.firestore.transact(read)

    def test_physical_expanded_and_per_bundle_budgets_still_fail_closed(self):
        path = document_path("hub_persistent_runs", "v2-budget")
        oversized = copy.deepcopy(self.compact)
        oversized["certificates"][0]["payload"] = "a" * 131072
        for store in self.stores:
            for compact, padding in ((self.compact, MAX_STORED_DOCUMENT_BYTES), (oversized, 0)):
                with self.subTest(backend=type(store).__name__, padding=padding):
                    history = canonical_json(compact) if store is self.firestore else compact
                    self.seed(
                        store,
                        path,
                        {"ownerUid": UID, "registryHistory": history, "opaque": "x" * padding},
                    )
                    with self.assertRaises(StoreUnavailable):
                        store.transact(lambda unit: self.read_all(unit, path))

    def test_bytes_are_canonical_and_private_snapshot_reaches_the_v2_decoder(self):
        from app import store as storage

        path = document_path("hub_vaults", self.f.owner)
        for raw in (b" " + canonical_json(self.compact), b"{}", b"[ ]", b"\xff"):
            self.seed(self.firestore, path, self.row | {"registryHistory": raw})
            with self.assertRaises(StoreUnavailable):
                self.firestore.transact(lambda unit: unit.get(path))
        source = self.encoded(self.sqlite)

        def mutate_original(value, **kwargs):
            source["registryHistory"]["bundles"][0]["entries"][0][0] = 2048
            source["version"] = 999
            return decode_storage_history_v2(value, **kwargs)

        with patch("app.store.decode_storage_history_v2", side_effect=mutate_original):
            self.assertEqual(self.row, storage._read_document(source, path=path))

    def test_original_root_signature_owner_time_and_revocation_checks_remain(self):
        path = document_path("hub_vaults", self.f.owner)
        for store in self.stores:
            for change in ("root", "checkpoint", "certificate", "owner"):
                row = copy.deepcopy(self.row)
                if change == "root":
                    row["rootKeyId"] = "A" * 43
                elif change == "owner":
                    row["ownerSubject"] = "wrong_owner"
                else:
                    signed = (
                        row["registryHistory"][-1]["checkpoint"]
                        if change == "checkpoint"
                        else row["registryHistory"][-1]["entries"][0]["certificate"]
                    )
                    signed["signature"] = "A" * 86
                self.seed(store, path, self.encoded(store, row))
                with (
                    self.subTest(change=change, backend=type(store).__name__),
                    self.assertRaises((ContractError, StoreUnavailable)),
                ):
                    store.transact(lambda unit: _current(unit, self.f.owner, 1000))
            self.seed(store, path, self.encoded(store))
            with self.assertRaises(ContractError):
                store.transact(lambda unit: _current(unit, self.f.owner, 499))

    def test_unrelated_collections_are_not_reinterpreted_and_v1_writer_stays_v1(self):
        from app.store import stored_document

        unrelated = document_path("hub_tasks", "unrelated")
        for store in self.stores:
            self.seed(store, unrelated, {"registryHistory": self.compact})
            self.assertEqual(
                {"registryHistory": self.compact}, store.transact(lambda unit: unit.get(unrelated))
            )
        path = document_path("hub_vaults", self.f.owner)
        row = self.row | {"registryHistory": self.history[:1], "version": 1, "operationCount": 1}
        stored = stored_document(row, path=path, project="synthetic", database="hub")
        self.assertEqual(REFERENCE_HISTORY_FORMAT, stored["registryHistory"]["format"])
        self.assertEqual(
            row, self.sqlite.transact(lambda unit: (unit.put(path, row), unit.get(path))[1])
        )


if __name__ == "__main__":
    unittest.main()
