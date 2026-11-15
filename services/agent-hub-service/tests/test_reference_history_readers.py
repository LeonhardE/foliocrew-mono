"""Reader-floor parity through SQLite and the real Firestore SDK RPC boundary."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fixtures import BOOT, OTHER_UID, UID, VaultFixture
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from google.cloud.firestore_v1._helpers import encode_dict
from google.cloud.firestore_v1.types import Document, RunQueryResponse
from test_firestore_store import MemoryRpc

from app.store import FirestoreHubStore, SQLiteHubStore, StoreUnavailable, document_path
from app.vaults import VaultService
from folioview_shared.encrypted.constants import MAX_READ_BYTES, MAX_STORED_DOCUMENT_BYTES
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json, strict_json_loads
from folioview_shared.encrypted.reference_history import (
    decode_reference_history,
    encode_reference_history,
)


class ReferenceHistoryReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = VaultFixture()
        for index in range(13):
            for suffix, role in (("sig", "agent_sig"), ("enc", "agent_enc")):
                cls.f.add_key(f"history_{index}_{suffix}", role, f"agent_{index}", f"conn_{index}")
        first = cls.f.make_bundle()
        previous = cls.f.verify(first)
        cls.history = [first]
        for _ in range(23):
            bundle = cls.f.make_bundle(previous=previous)
            # The same exact Root-signed JWS is retained across checkpoints.
            bundle["entries"] = copy.deepcopy(first["entries"])
            previous = cls.f.verify(bundle, previous=previous)
            cls.history.append(bundle)
        cls.row = {
            "ownerSubject": cls.f.owner,
            "vaultId": cls.f.vault,
            "rootJwk": cls.f.root_public,
            "rootKeyId": cls.f.root_id,
            "registryHistory": cls.history,
            "archive": cls.f.bootstrap()["archive"],
            "version": len(cls.history),
            "sources": [],
            "operationCount": len(cls.history),
        }
        cls.compact = encode_reference_history(cls.history)
        assert MAX_STORED_DOCUMENT_BYTES < len(canonical_json(cls.row)) < MAX_READ_BYTES

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

    def seed(self, store, path, value):
        if store is self.sqlite:
            with store.connect() as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO hub_documents(path,body) VALUES(?,?)",
                    (path, canonical_json(value).decode()),
                )
        else:
            self.rpc.documents[self.client.document(path)._document_path] = copy.deepcopy(value)

    def snapshot(self, store):
        if store is self.sqlite:
            with store.connect() as connection:
                return connection.execute(
                    "SELECT path,body FROM hub_documents ORDER BY path"
                ).fetchall()
        return copy.deepcopy(self.rpc.documents)

    def compact_row(self, store, row=None):
        row = self.row if row is None else row
        compact = encode_reference_history(row["registryHistory"])
        return {
            **row,
            "registryHistory": canonical_json(compact) if store is self.firestore else compact,
        }

    def test_large_current_restores_exact_response_without_migration_or_mutable_aliases(self):
        path = document_path("hub_vaults", self.f.owner)
        expected = {
            "contractVersion": self.history[0]["contractVersion"],
            "vault": {
                key: self.row[key]
                for key in (
                    "vaultId",
                    "rootJwk",
                    "rootKeyId",
                    "registryHistory",
                    "archive",
                    "version",
                )
            },
            "sources": [],
        }
        for store in self.stores:
            with self.subTest(backend=type(store).__name__):
                self.seed(store, path, self.compact_row(store))
                before = self.snapshot(store)
                service = VaultService(store, clock=lambda: 1000)
                self.assertEqual(service.current(UID), expected)
                self.assertIsNone(service.current(OTHER_UID)["vault"])

                def read(unit):
                    first = unit.get(path)
                    first["registryHistory"][0]["entries"][0]["active"] = False
                    second = unit.get_many([path])[path]
                    self.assertEqual(second, self.row)
                    self.assertIsNot(
                        second["registryHistory"][0]["entries"][0]["certificate"],
                        second["registryHistory"][1]["entries"][0]["certificate"],
                    )
                    return second

                self.assertEqual(store.transact(read), self.row)
                self.assertEqual(self.snapshot(store), before)
        self.assertFalse(
            any(kind == "commit" and kwargs["request"]["writes"] for kind, kwargs in self.rpc.calls)
        )

    def test_small_legacy_arrays_bytes_and_reference_forms_read_identically(self):
        small = {**self.row, "registryHistory": self.history[:1], "version": 1, "operationCount": 1}
        path = document_path("hub_vaults", self.f.owner)
        for store in self.stores:
            forms = [small["registryHistory"], encode_reference_history(small["registryHistory"])]
            if store is self.firestore:
                forms += [canonical_json(form) for form in forms]
            for history in forms:
                with self.subTest(
                    backend=type(store).__name__, history_type=type(history).__name__
                ):
                    self.seed(store, path, {**small, "registryHistory": history})
                    before = self.snapshot(store)
                    both = store.transact(lambda unit: (unit.get(path), unit.get_many([path])))
                    self.assertEqual(both, (small, {path: small}))
                    self.assertEqual(before, self.snapshot(store))

    def test_persistent_run_scan_and_gets_restore_history_and_keep_tombstones(self):
        path = document_path("hub_persistent_runs", "run")
        tombstone = document_path("hub_persistent_runs", "retired")
        row = {"ownerUid": UID, "registryHistory": self.history, "manifestJson": "opaque"}
        retired = {"ownerUid": UID, "retiredTaskContent": True}
        for store in self.stores:
            with self.subTest(backend=type(store).__name__):
                self.seed(store, path, self.compact_row(store, row))
                self.seed(store, tombstone, retired)
                before = self.snapshot(store)
                if store is self.firestore:

                    def query(**kwargs):
                        self.rpc.record("query", kwargs)
                        return iter(
                            RunQueryResponse(
                                document=Document(name=name, fields=encode_dict(value))
                            )
                            for name, value in sorted(self.rpc.documents.items())
                        )

                    self.rpc.run_query = query
                actual = store.transact(
                    lambda unit: (
                        unit.get(path),
                        unit.get_many([path, tombstone]),
                        unit.scan_owner("hub_persistent_runs", "ownerUid", UID),
                    )
                )
                self.assertEqual(actual[0], row)
                self.assertEqual(actual[1], {path: row, tombstone: retired})
                self.assertEqual(dict(actual[2]), {path: row, tombstone: retired})
                self.assertEqual(before, self.snapshot(store))

    def test_run_read_budget_separates_history_from_manifest_without_raising_physical_limit(self):
        path = document_path("hub_persistent_runs", "large-manifest")
        row = {"ownerUid": UID, "registryHistory": self.history, "manifestJson": "x" * 400000}
        self.assertGreater(len(canonical_json(row)), MAX_READ_BYTES)
        self.assertLess(len(canonical_json(row)), MAX_READ_BYTES + MAX_STORED_DOCUMENT_BYTES)
        for store in self.stores:
            self.seed(store, path, self.compact_row(store, row))
            self.assertEqual(store.transact(lambda unit: unit.get(path)), row)

    def test_physical_and_expanded_bounds_reject_before_cache_admission(self):
        path = document_path("hub_vaults", self.f.owner)
        # Both physically small but expanded too large, and physically oversized.
        for padding in (300000, MAX_STORED_DOCUMENT_BYTES):
            for store in self.stores:
                with self.subTest(padding=padding, backend=type(store).__name__):
                    stored = {**self.compact_row(store), "opaque": "x" * padding}
                    self.seed(store, path, stored)
                    for batch in (False, True):
                        with self.assertRaises(StoreUnavailable):
                            store.transact(
                                lambda unit, batch=batch: (
                                    unit.get_many([path]) if batch else unit.get(path)
                                )
                            )
        # A Run cannot expand its history above 1MiB, even with spare row budget.
        encoded = copy.deepcopy(self.compact)
        encoded["bundles"] += copy.deepcopy(encoded["bundles"][:8])
        path = document_path("hub_persistent_runs", "history-bomb")
        for store in self.stores:
            history = canonical_json(encoded) if store is self.firestore else encoded
            self.seed(store, path, {"ownerUid": UID, "registryHistory": history})
            with self.assertRaises(StoreUnavailable):
                store.transact(lambda unit: unit.get(path))

    def test_malformed_reference_rows_are_not_empty_or_successfully_cached(self):
        path = document_path("hub_persistent_runs", "corrupt")
        valid = {"ownerUid": UID, "registryHistory": self.history[:1]}
        compact = encode_reference_history(valid["registryHistory"])
        malformed = []
        for mutate in (
            lambda value: value.update(format="unknown"),
            lambda value: value.update(extra=True),
            lambda value: value["bundles"][0]["entries"][0].__setitem__(0, True),
            lambda value: value["bundles"][0]["entries"][0].__setitem__(0, 999),
            lambda value: value["bundles"][0]["entries"][0].__setitem__(1, "true"),
            lambda value: value["bundles"][0]["bundle"].update(entries=[]),
        ):
            altered = copy.deepcopy(compact)
            mutate(altered)
            malformed.append(altered)
        for store in self.stores:
            for altered in malformed:
                with self.subTest(backend=type(store).__name__):
                    value = canonical_json(altered) if store is self.firestore else altered
                    self.seed(store, path, {**valid, "registryHistory": value})
                    with self.assertRaises(StoreUnavailable):
                        store.transact(lambda unit: unit.get_many([path]))
            if store is self.firestore:

                def retry(unit, store=store):
                    with self.assertRaises(StoreUnavailable):
                        unit.get_many([path])
                    self.assertEqual(unit._reads, {})
                    self.seed(store, path, self.compact_row(store, valid))
                    self.assertEqual(unit.get(path), valid)

                store.transact(retry)

    def test_native_float_and_boolean_refs_rejected_by_single_batch_and_owner_scan(self):
        path = document_path("hub_persistent_runs", "native-ref-types")
        for reference in (0.0, -0.0, True):
            for store in self.stores:
                with self.subTest(reference=repr(reference), backend=type(store).__name__):
                    compact = encode_reference_history(self.history[:1])
                    compact["bundles"][0]["entries"][0][0] = reference
                    row = {"ownerUid": UID, "registryHistory": compact}
                    if store is self.sqlite:
                        # Simulate a stored noncanonical native number. Canonical
                        # test seeding would itself turn 0.0/-0.0 into integer 0.
                        with store.connect() as connection:
                            connection.execute(
                                "INSERT OR REPLACE INTO hub_documents(path,body) VALUES(?,?)",
                                (path, json.dumps(row)),
                            )
                    else:
                        # The real SDK retains double_value, not integer_value.
                        self.seed(store, path, row)

                        def query(**kwargs):
                            self.rpc.record("query", kwargs)
                            return iter(
                                RunQueryResponse(
                                    document=Document(name=name, fields=encode_dict(value))
                                )
                                for name, value in self.rpc.documents.items()
                            )

                        self.rpc.run_query = query
                    for operation in ("single", "batch", "scan"):

                        def read(unit, operation=operation):
                            if operation == "single":
                                return unit.get(path)
                            if operation == "batch":
                                return unit.get_many([path])
                            return unit.scan_owner("hub_persistent_runs", "ownerUid", UID)

                        with self.subTest(operation=operation), self.assertRaises(StoreUnavailable):
                            store.transact(read)

    def test_noncanonical_bytes_and_unrelated_collection_bytes_stay_rejected(self):
        path = document_path("hub_vaults", self.f.owner)
        for raw in (b" " + canonical_json(self.compact), b"{}", b"[ ]", b"[1,]", b"\xff"):
            self.seed(self.firestore, path, {**self.row, "registryHistory": raw})
            with self.assertRaises(StoreUnavailable):
                self.firestore.transact(lambda unit: unit.get(path))
        unrelated = document_path("hub_tasks", "unrelated")
        self.seed(self.firestore, unrelated, {"registryHistory": canonical_json(self.compact)})
        with self.assertRaises(StoreUnavailable):
            self.firestore.transact(lambda unit: unit.get(unrelated))
        for store in self.stores:
            self.seed(store, unrelated, {"registryHistory": self.compact})
            self.assertEqual(
                store.transact(lambda unit: unit.get(unrelated)), {"registryHistory": self.compact}
            )  # No new format recognition or history expansion outside the whitelist.

    def test_native_row_numbers_keep_types_for_original_authority_and_generic_reads(self):
        path = document_path("hub_vaults", self.f.owner)
        for field in ("version", "operationCount", "sourceEpoch"):
            for store in self.stores:
                row = self.compact_row(store)
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
                if store is self.sqlite:
                    with store.connect() as connection:
                        connection.execute(
                            "INSERT OR REPLACE INTO hub_documents(path,body) VALUES(?,?)",
                            (path, json.dumps(row)),
                        )
                else:
                    self.seed(store, path, row)
                with self.subTest(field=field, backend=type(store).__name__):
                    actual = store.transact(
                        lambda unit: (unit.get(path), unit.get_many([path])[path])
                    )
                    self.assertTrue(
                        all(
                            type(
                                value["sources"][0][field]
                                if field == "sourceEpoch"
                                else value[field]
                            )
                            is float
                            for value in actual
                        )
                    )
                    with self.assertRaises((ContractError, StoreUnavailable)):
                        VaultService(store, clock=lambda: 1000).current(UID)
        # Unrelated rows and retention tombstones must also retain native types.
        path = document_path("hub_persistent_runs", "native-row-numbers")
        row = {"ownerUid": UID, "version": 1.0, "sourceEpoch": -0.0}
        for store in self.stores:
            if store is self.sqlite:
                with store.connect() as connection:
                    connection.execute(
                        "INSERT OR REPLACE INTO hub_documents(path,body) VALUES(?,?)",
                        (path, json.dumps(row)),
                    )
            else:
                self.rpc.documents.clear()
                self.seed(store, path, row)

                def query(**kwargs):
                    self.rpc.record("query", kwargs)
                    return iter(
                        RunQueryResponse(document=Document(name=name, fields=encode_dict(value)))
                        for name, value in self.rpc.documents.items()
                    )

                self.rpc.run_query = query
            actual = store.transact(
                lambda unit: (
                    unit.get(path),
                    unit.get_many([path])[path],
                    unit.scan_owner("hub_persistent_runs", "ownerUid", UID)[0][1],
                )
            )
            self.assertTrue(all(type(value["version"]) is float for value in actual))
            self.assertTrue(all(type(value["sourceEpoch"]) is float for value in actual))

    def test_original_root_signature_owner_and_time_verification_still_runs(self):
        path = document_path("hub_vaults", self.f.owner)
        for store in self.stores:
            for changed in ("root", "checkpoint", "certificate", "owner"):
                row = copy.deepcopy(self.row)
                if changed == "root":
                    row["rootKeyId"] = "A" * 43
                elif changed == "owner":
                    row["ownerSubject"] = "different_owner"
                else:
                    signed = (
                        row["registryHistory"][-1]["checkpoint"]
                        if changed == "checkpoint"
                        else row["registryHistory"][-1]["entries"][0]["certificate"]
                    )
                    signed["signature"] = "A" * 86
                self.seed(store, path, self.compact_row(store, row))
                with (
                    self.subTest(changed=changed, backend=type(store).__name__),
                    self.assertRaises((StoreUnavailable, ContractError)),
                ):
                    VaultService(store, clock=lambda: 1000).current(UID)
            self.seed(store, path, self.compact_row(store))
            with self.assertRaises(ContractError):
                VaultService(store, clock=lambda: 499).current(UID)

    def test_reader_release_keeps_existing_writes_and_large_write_rejection_atomic(self):
        for store in self.stores:
            with self.subTest(backend=type(store).__name__):
                fixture = VaultFixture()
                service = VaultService(store, clock=lambda: 1000)
                service.bootstrap(UID, fixture.bootstrap(), BOOT)
                path = document_path("hub_vaults", fixture.owner)
                before = self.snapshot(store)
                if store is self.sqlite:
                    stored = strict_json_loads(dict(before)[path])
                else:
                    stored = copy.deepcopy(before[self.client.document(path)._document_path])
                    self.assertIs(type(stored["registryHistory"]), bytes)
                    stored["registryHistory"] = strict_json_loads(stored["registryHistory"])
                self.assertIs(type(stored["registryHistory"]), list)
                with self.assertRaises(ContractError) as failure:
                    store.transact(lambda unit, path=path: unit.put(path, self.row))
                self.assertEqual(failure.exception.code, "payload_too_large")
                self.assertEqual(self.snapshot(store), before)

    def test_private_storage_snapshot_is_the_snapshot_passed_to_decoder(self):
        from app import store as storage

        source = {**self.row, "registryHistory": copy.deepcopy(self.compact)}
        expected = copy.deepcopy(source)

        def mutate_original(value, **kwargs):
            source["registryHistory"]["bundles"][0]["entries"][0][0] = 999
            source["version"] = 999
            return decode_reference_history(value, **kwargs)

        with patch("app.store.decode_reference_history", side_effect=mutate_original):
            result = storage._read_document(source, path=document_path("hub_vaults", self.f.owner))
        self.assertEqual(result, self.row)
        self.assertNotEqual(source, expected)
