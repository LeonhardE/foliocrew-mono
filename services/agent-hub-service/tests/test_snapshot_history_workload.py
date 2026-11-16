"""Real24/25-generation storage.v1 payloads use the original validators and DTOs."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fixtures import UID, VaultFixture
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from google.cloud.firestore_v1._helpers import encode_dict
from google.cloud.firestore_v1.types import Document
from test_resource_display import Sources
from test_snapshot_reads import SnapshotRpc

from app import vaults
from app.resource_display import ResourceDisplayService
from app.snapshot_reads import sqlite_snapshot
from app.store import FirestoreHubStore, SQLiteHubStore, StoreUnavailable, document_path
from app.vaults import VaultService
from folioview_shared.encrypted.authority import RegistryCertificateMemo
from folioview_shared.encrypted.constants import MAX_READ_BYTES, MAX_STORED_DOCUMENT_BYTES
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json, strict_json_loads
from folioview_shared.encrypted.reference_history import REFERENCE_HISTORY_FORMAT


class SnapshotHistoryWorkloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f = VaultFixture()
        cls.histories = {}
        history = [copy.deepcopy(cls.f.bundle)]
        previous = cls.f.registry
        memo = RegistryCertificateMemo()
        for generation in range(2, 26):
            for suffix, role in (("sig", "agent_sig"), ("enc", "agent_enc")):
                cls.f.add_key(
                    f"history_{generation:032x}_{suffix}",
                    role,
                    f"agent_{generation:032x}",
                    f"connection_{generation:032x}",
                )
            revoked = (f"history_{2:032x}_sig", f"history_{2:032x}_enc") if generation >= 24 else ()
            bundle = cls.f.make_bundle(previous=previous, revoked=revoked)
            known = {
                entry["certificate"]["payload"]: entry["certificate"]
                for entry in history[-1]["entries"]
            }
            for entry in bundle["entries"]:
                entry["certificate"] = copy.deepcopy(
                    known.get(entry["certificate"]["payload"], entry["certificate"])
                )
            previous = cls.f.verify(bundle, previous=previous, signature_memo=memo)
            history.append(bundle)
            if generation in (24, 25):
                cls.histories[generation] = copy.deepcopy(history)
        cls.final_registry = previous

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.sqlite = SQLiteHubStore(Path(directory.name) / "snapshot.sqlite")
        self.client = firestore.Client(
            project="synthetic-hub", database="agent-hub", credentials=AnonymousCredentials()
        )
        self.addCleanup(self.client.close)
        self.rpc = SnapshotRpc(self.client)
        self.client._firestore_api_internal = self.rpc
        self.firestore = FirestoreHubStore("synthetic-hub", "agent-hub", client=self.client)
        self.path = document_path("hub_vaults", self.f.owner)

    def row(self, generation):
        return {
            "ownerSubject": self.f.owner,
            "vaultId": self.f.vault,
            "rootJwk": self.f.root_public,
            "rootKeyId": self.f.root_id,
            "registryHistory": copy.deepcopy(self.histories[generation]),
            "archive": self.f.bootstrap()["archive"],
            "version": generation + 2,
            "operationCount": generation + 2,
            "sources": [
                {
                    "resourceRef": self.f.resource | {"resourceId": f"holdings_{index}"},
                    "sourceEpoch": 1,
                }
                for index in range(2)
            ],
        }

    def service(self, store):
        return ResourceDisplayService(VaultService(store, clock=lambda: 1000), Sources())

    def seed(self, store, row):
        store.transact(lambda unit: unit.put(self.path, row))
        self.rpc.calls.clear()

    def physical(self):
        value = self.rpc.documents[self.client.document(self.path)._document_path]
        self.assertIs(type(value["registryHistory"]), bytes)
        compact = strict_json_loads(value["registryHistory"], max_bytes=MAX_STORED_DOCUMENT_BYTES)
        self.assertEqual(compact["format"], REFERENCE_HISTORY_FORMAT)
        physical_json = {**value, "registryHistory": compact}
        sdk = Document(
            name=self.client.document(self.path)._document_path, fields=encode_dict(value)
        )
        return len(canonical_json(physical_json)), sdk._pb.ByteSize(), len(value["registryHistory"])

    def test_24_25_generation_physical_reference_bytes_equal_original_callback_dtos_and_rpc_counts(
        self,
    ):
        for generation in (24, 25):
            with self.subTest(generation=generation):
                row = self.row(generation)
                self.assertLess(len(canonical_json(row)), MAX_READ_BYTES)
                self.assertGreater(len(canonical_json(row)), MAX_STORED_DOCUMENT_BYTES)
                self.seed(self.firestore, row)
                json_size, sdk_size, history_bytes = self.physical()
                self.assertLess(json_size, MAX_STORED_DOCUMENT_BYTES)
                self.assertLess(sdk_size, MAX_STORED_DOCUMENT_BYTES)
                self.assertGreater(history_bytes, 60_000)
                self.service(self.firestore).read(UID)  # Establish normal path-only hints.
                self.rpc.calls.clear()
                # Same callbacks/view/physical readers, but the original real
                # SDK Begin→BatchGet→Commit lifecycle supplies this baseline.
                with patch.object(
                    self.firestore,
                    "read_snapshot",
                    lambda paths, callback: sqlite_snapshot(self.firestore, paths, callback),
                ):
                    original = self.service(self.firestore).read(UID)
                self.assertEqual(
                    [kind for kind, _ in self.rpc.calls], ["begin", "get", "commit"] * 2
                )
                self.rpc.calls.clear()
                optimized = self.service(self.firestore).read(UID)
                self.assertEqual([kind for kind, _ in self.rpc.calls], ["get", "commit"] * 2)
                self.assertEqual(optimized, original)
                self.assertTrue(
                    all(
                        not args["request"]["writes"]
                        for kind, args in self.rpc.calls
                        if kind == "commit"
                    )
                )
                self.seed(self.sqlite, row)
                self.assertEqual(self.service(self.sqlite).read(UID), optimized)
                # Revocation is signed retained history, not discarded by refs.
                self.assertNotIn(
                    self.f.kid(f"history_{2:032x}_sig"), self.final_registry.active_key_ids
                )

    def test_large_retry_uses_fresh_clock_and_root_but_keeps_existing_static_memo(self):
        self.seed(self.firestore, self.row(25))
        memo = {}
        now = iter((1000, 523)).__next__  # Final checkpoint issued at524.
        self.rpc.aborts = 1

        def callback(unit):
            return vaults._verify_row(
                unit.get(self.path), self.f.owner, now(), unit=unit, registry_cache=memo
            )

        with self.assertRaises(ContractError) as rejected:
            self.firestore.read_snapshot(lambda: [self.path], callback)
        self.assertEqual(rejected.exception.code, "registry_conflict")
        self.assertEqual(len(memo), 1, "existing successful static history evidence is not cleared")
        self.assertEqual([kind for kind, _ in self.rpc.calls], ["get", "commit", "get", "rollback"])

    def test_bad_large_checkpoint_is_rejected_by_both_original_and_combined_snapshots(self):
        row = self.row(24)
        row["registryHistory"][-1]["checkpoint"]["signature"] = "A" * 86
        self.seed(self.firestore, row)
        for combined in (False, True):
            with self.subTest(combined=combined):

                def callback(unit):
                    return vaults._verify_row(unit.get(self.path), self.f.owner, 1000, unit=unit)

                self.rpc.calls.clear()
                with self.assertRaises((ContractError, StoreUnavailable)):
                    if combined:
                        self.firestore.read_snapshot(lambda: [self.path], callback)
                    else:
                        sqlite_snapshot(self.firestore, lambda: [self.path], callback)
                self.assertTrue(all(kind != "commit" for kind, _ in self.rpc.calls))
                self.assertEqual(sum(kind == "rollback" for kind, _ in self.rpc.calls), 1)


if __name__ == "__main__":
    unittest.main()
