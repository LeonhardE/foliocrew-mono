"""Normal Owner updates retain every signed generation across both storage engines."""

import copy
import tempfile
import unittest
from pathlib import Path

import test_persistent_execution as executions
from fixtures import UID, VaultFixture
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from google.cloud.firestore_v1._helpers import encode_dict
from google.cloud.firestore_v1.types import Document
from test_firestore_store import MemoryRpc

from app.store import FirestoreHubStore, SQLiteHubStore, document_path
from app.vaults import VaultService
from folioview_shared.encrypted.constants import (
    CONTRACT_VERSION,
    MAX_HTTP_WRITE_BYTES,
    MAX_READ_BYTES,
    MAX_STORED_DOCUMENT_BYTES,
)
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json, strict_json_loads
from folioview_shared.encrypted.reference_history import REFERENCE_HISTORY_FORMAT


class ReferenceHistoryWriterTests(unittest.TestCase):
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

    def snapshot(self, store):
        if store is self.sqlite:
            with store.connect() as connection:
                return connection.execute(
                    "SELECT path,body FROM hub_documents ORDER BY path"
                ).fetchall()
        return copy.deepcopy(self.rpc.documents)

    def stored(self, store, path):
        if store is self.sqlite:
            return strict_json_loads(dict(self.snapshot(store))[path])
        value = copy.deepcopy(self.rpc.documents[self.client.document(path)._document_path])
        value["registryHistory"] = strict_json_loads(value["registryHistory"])
        return value

    def legacy_row(self, f):
        for index in range(13):
            for suffix, role in (("sig", "agent_sig"), ("enc", "agent_enc")):
                f.add_key(f"history_{index}_{suffix}", role, f"agent_{index}", f"conn_{index}")
        first = f.make_bundle()
        previous = f.verify(first)
        history = [first]
        for _ in range(21):
            bundle = f.make_bundle(previous=previous)
            bundle["entries"] = copy.deepcopy(first["entries"])
            previous = f.verify(bundle, previous=previous)
            history.append(bundle)
        row = {
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
        self.assertLess(len(canonical_json(row)), MAX_STORED_DOCUMENT_BYTES)
        return row, previous

    def seed_legacy(self, store, path, row):
        if store is self.sqlite:
            with store.connect() as connection:
                connection.execute(
                    "INSERT INTO hub_documents(path,body) VALUES(?,?)",
                    (path, canonical_json(row).decode()),
                )
        else:
            self.rpc.documents.clear()
            self.rpc.calls.clear()
            value = {**row, "registryHistory": canonical_json(row["registryHistory"])}
            name = self.client.document(path)._document_path
            self.assertLess(
                len(Document(name=name, fields=encode_dict(value))._pb.SerializeToString()),
                MAX_STORED_DOCUMENT_BYTES,
            )
            self.rpc.documents[name] = value

    def test_normal_owner_update_crosses_legacy_capacity_and_keeps_atomic_cas_and_replay(self):
        for store in (self.sqlite, self.firestore):
            with self.subTest(backend=type(store).__name__):
                f = VaultFixture()
                row, previous = self.legacy_row(f)
                path = document_path("hub_vaults", f.owner)
                self.seed_legacy(store, path, row)
                service = VaultService(store, clock=lambda: 1000)
                before = self.snapshot(store)
                self.assertEqual(
                    service.current(UID)["vault"]["registryHistory"], row["registryHistory"]
                )
                self.assertEqual(self.snapshot(store), before, "legacy reads cannot migrate")
                for suffix, role in (("sig", "device_sig"), ("enc", "device_enc")):
                    f.add_key(f"second_device_{suffix}", role, "device_second")
                bundle = f.make_bundle(previous=previous)
                bundle["entries"] = (
                    copy.deepcopy(row["registryHistory"][-1]["entries"]) + bundle["entries"][-2:]
                )
                expected_history = copy.deepcopy(row["registryHistory"])
                for generation in (23, 24):
                    body = {
                        "contractVersion": CONTRACT_VERSION,
                        "expectedVersion": generation - 1,
                        "registryBundle": bundle,
                    }
                    self.assertLess(len(canonical_json(body)), MAX_HTTP_WRITE_BYTES)
                    operation = f"synthetic_reference_update_{generation:04}"
                    result = service.update_registry(UID, f.vault, body, operation)
                    self.assertEqual(service.update_registry(UID, f.vault, body, operation), result)
                    row = store.transact(lambda unit, path=path: unit.get(path))
                    self.assertEqual(row["registryHistory"], result["vault"]["registryHistory"])
                    expected_history.append(copy.deepcopy(bundle))
                    self.assertEqual(row["registryHistory"], expected_history)
                    self.assertEqual(len(row["registryHistory"]), generation)
                    self.assertGreater(len(canonical_json(row)), MAX_STORED_DOCUMENT_BYTES)
                    self.assertLess(len(canonical_json(row)), MAX_READ_BYTES)
                    stored = self.stored(store, path)
                    self.assertEqual(stored["registryHistory"]["format"], REFERENCE_HISTORY_FORMAT)
                    self.assertLess(len(canonical_json(stored)), MAX_STORED_DOCUMENT_BYTES)
                    current = self.snapshot(store)
                    with self.assertRaises(ContractError) as conflict:
                        service.update_registry(UID, f.vault, body, operation + "_conflict")
                    self.assertEqual(conflict.exception.code, "version_conflict")
                    self.assertEqual(self.snapshot(store), current)
                    previous = f.verify(bundle, previous=previous)
                    next_bundle = f.make_bundle(previous=previous)
                    next_bundle["entries"] = copy.deepcopy(bundle["entries"])
                    broken = copy.deepcopy(next_bundle)
                    broken["checkpoint"]["signature"] = "A" * 86
                    with self.assertRaises(ContractError):
                        service.update_registry(
                            UID,
                            f.vault,
                            {
                                "contractVersion": CONTRACT_VERSION,
                                "expectedVersion": generation,
                                "registryBundle": broken,
                            },
                            operation + "_invalid",
                        )
                    self.assertEqual(self.snapshot(store), current)
                    bundle = next_bundle

    def test_persistent_freeze_above_legacy_limit_uses_actual_firestore_sdk_and_immutable_replay(
        self,
    ):
        case = executions.PersistentExecutionTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        with case.fx.store.connect() as connection:
            rows = connection.execute("SELECT path,body FROM hub_documents").fetchall()
        for path, body in rows:
            self.rpc.documents[self.client.document(path)._document_path] = strict_json_loads(body)
            row = self.rpc.documents[self.client.document(path)._document_path]
            if (
                path.startswith(("hub_vaults/", "hub_persistent_runs/"))
                and "registryHistory" in row
            ):
                row["registryHistory"] = canonical_json(row["registryHistory"])
        case.fx.store = self.firestore
        case.fx.vaults.store = self.firestore
        case.service = case.new_service()
        case.test_freeze_uses_expanded_budget_for_already_verified_registry_history()
        runs = [
            (name, value)
            for name, value in self.rpc.documents.items()
            if "/hub_persistent_runs/" in name
        ]
        self.assertEqual(len(runs), 1)
        name, value = runs[0]
        self.assertIs(type(value["registryHistory"]), bytes)
        self.assertEqual(
            strict_json_loads(value["registryHistory"])["format"], REFERENCE_HISTORY_FORMAT
        )
        self.assertLess(
            len(Document(name=name, fields=encode_dict(value))._pb.SerializeToString()),
            MAX_STORED_DOCUMENT_BYTES,
        )
