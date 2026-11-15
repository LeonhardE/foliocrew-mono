"""Fresh first-enrollment authorization on actual SDK retries and SQLite waits."""

import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from fixtures import BOOT, SOURCE, UID, VaultFixture
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from test_firestore_store import MemoryRpc

from app.api import get_service, require_owner
from app.fences import FenceService
from app.main import app
from app.store import FirestoreHubStore, SQLiteHubStore, document_path
from app.vaults import VaultService
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError


class BootstrapRetryTimeTests(unittest.TestCase):
    def setUp(self):
        self.client = firestore.Client(
            project="synthetic-hub", database="agent-hub", credentials=AnonymousCredentials()
        )
        self.addCleanup(self.client.close)
        self.rpc = MemoryRpc(self.client)
        self.client._firestore_api_internal = self.rpc
        self.store = FirestoreHubStore("synthetic-hub", "agent-hub", client=self.client)
        self.now = 1000
        self.service = VaultService(self.store, clock=lambda: self.now)
        self.f = VaultFixture()
        self.expire_at(1001)

    def expire_at(self, expiry):
        for certificate in self.f.certificates.values():
            certificate["expiresAt"] = expiry
        self.f.bundle = self.f.make_bundle()
        self.f.registry = self.f.verify(self.f.bundle)

    def abort_and_advance(self, now):
        def advance():
            self.now = now

        self.rpc.aborts, self.rpc.before_abort = 1, advance

    def commits(self):
        return [len(args["request"]["writes"]) for kind, args in self.rpc.calls if kind == "commit"]

    def attempts(self):
        return sum(kind == "begin" for kind, _ in self.rpc.calls)

    def post(self):
        app.dependency_overrides[get_service] = lambda: self.service
        app.dependency_overrides[require_owner] = lambda: SimpleNamespace(uid=UID)
        try:
            with TestClient(app) as http:
                return http.post(
                    "/api/v2/vaults",
                    headers={"X-FolioView-Contract": CONTRACT_VERSION, "Idempotency-Key": BOOT},
                    json=self.f.bootstrap(),
                )
        finally:
            app.dependency_overrides.clear()

    def test_http_retry_across_expiry_rejects_new_vault_and_operation_atomically(self):
        self.abort_and_advance(1002)
        response = self.post()
        self.assertEqual(403, response.status_code)
        self.assertEqual("key_authorization_required", response.json()["error"]["code"])
        self.assertEqual("no-store", response.headers["cache-control"])
        self.assertEqual(2, self.attempts())
        self.assertEqual([2], self.commits(), "only the aborted attempt may stage writes")
        self.assertEqual({}, self.rpc.documents)
        self.assertTrue(any(kind == "rollback" for kind, _ in self.rpc.calls))

    def test_http_fresh_expired_request_still_rejects_before_transaction(self):
        self.now = 1002
        response = self.post()
        self.assertEqual(403, response.status_code)
        self.assertEqual("key_authorization_required", response.json()["error"]["code"])
        self.assertEqual(0, self.attempts())
        self.assertEqual([], self.commits())
        self.assertEqual({}, self.rpc.documents)

    def test_http_nonexpired_retry_keeps_original_response_and_atomic_two_writes(self):
        self.expire_at(1005)
        self.abort_and_advance(1002)
        response = self.post()
        self.assertEqual(201, response.status_code)
        self.assertEqual(2, self.attempts())
        self.assertEqual([2, 2], self.commits())
        self.assertEqual(2, len(self.rpc.documents))
        self.assertEqual(self.service.current(UID), response.json())

    def test_retry_rechecks_complete_registry_when_clock_precedes_checkpoint(self):
        self.abort_and_advance(self.f.registry.issued_at - 1)
        with self.assertRaises(ContractError) as error:
            self.service.bootstrap(UID, self.f.bootstrap(), BOOT)
        self.assertEqual("registry_conflict", error.exception.code)
        self.assertEqual(2, self.attempts())
        self.assertEqual([2], self.commits())
        self.assertEqual({}, self.rpc.documents)

    def test_exact_committed_replay_survives_retry_across_selected_key_expiry(self):
        saved = self.service.bootstrap(UID, self.f.bootstrap(), BOOT)
        before = copy.deepcopy(self.rpc.documents)
        self.rpc.calls.clear()
        self.abort_and_advance(1002)
        self.assertEqual(saved, self.service.bootstrap(UID, self.f.bootstrap(), BOOT))
        self.assertEqual(2, self.attempts())
        self.assertEqual([0, 0], self.commits())
        self.assertEqual(before, self.rpc.documents)

    def test_retry_replay_projects_winner_current_revocations_cas_and_source_fence(self):
        self.expire_at(5000)
        original = copy.deepcopy(self.f.bootstrap())
        winner = {}

        def win():
            self.rpc.before_abort = None
            self.service.bootstrap(UID, original, BOOT)
            source = self.service.create_source(
                UID,
                self.f.vault,
                SOURCE,
                self.f.control(),
                "synthetic_source_create_0001",
                self.f.kid("device_sig"),
            )["source"]
            self.f.add_key("new_sig", "device_sig", "device_new")
            self.f.add_key("new_enc", "device_enc", "device_new")
            bundle = self.f.make_bundle(
                previous=self.f.registry, revoked=("device_sig", "device_enc")
            )
            self.service.update_registry(
                UID,
                self.f.vault,
                {
                    "contractVersion": CONTRACT_VERSION,
                    "expectedVersion": 2,
                    "registryBundle": bundle,
                },
                "synthetic_registry_update_0001",
            )
            FenceService(self.store, clock=lambda: self.now).invalidate(
                {
                    "contractVersion": CONTRACT_VERSION,
                    "ownerSubject": self.f.owner,
                    "mutationId": "synthetic_source_fence_0001",
                    "ref": source["resourceRef"],
                    "expectedSourceEpoch": 1,
                    "newSourceEpoch": 2,
                    "reason": "account_scope_changed",
                },
                source_service="portfolio",
            )
            winner["response"] = self.service.current(UID)
            winner["documents"] = copy.deepcopy(self.rpc.documents)

        self.rpc.aborts, self.rpc.before_abort = 1, win
        replayed = self.service.bootstrap(UID, original, BOOT)
        self.assertEqual(winner["response"], replayed)
        self.assertEqual(winner["documents"], self.rpc.documents)
        self.assertEqual(3, replayed["vault"]["version"])
        self.assertEqual(2, len(replayed["vault"]["registryHistory"]))
        self.assertEqual(2, replayed["sources"][0]["sourceEpoch"])
        self.assertEqual(original["archive"], replayed["vault"]["archive"])

    def test_retry_keeps_competing_root_winner_without_overwrite(self):
        competing = VaultFixture()
        winner = {}

        def win():
            self.rpc.before_abort = None
            self.service.bootstrap(UID, competing.bootstrap(), BOOT + "_winner")
            winner.update(copy.deepcopy(self.rpc.documents))

        self.rpc.aborts, self.rpc.before_abort = 1, win
        with self.assertRaises(ContractError) as error:
            self.service.bootstrap(UID, self.f.bootstrap(), BOOT)
        self.assertEqual("version_conflict", error.exception.code)
        self.assertEqual(winner, self.rpc.documents)
        self.assertEqual(competing.root_id, self.service.current(UID)["vault"]["rootKeyId"])

    def test_sqlite_transaction_wait_rechecks_new_enrollment_time(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteHubStore(Path(directory) / "hub.sqlite3")
            service = VaultService(store, clock=lambda: self.now)
            transact = store.transact

            def delayed_start(callback):
                self.now = 1002
                return transact(callback)

            with patch.object(store, "transact", side_effect=delayed_start):
                with self.assertRaises(ContractError) as error:
                    service.bootstrap(UID, self.f.bootstrap(), BOOT)
            self.assertEqual("key_authorization_required", error.exception.code)
            self.assertIsNone(
                store.transact(lambda unit: unit.get(document_path("hub_vaults", self.f.owner)))
            )
            self.assertIsNone(
                store.transact(
                    lambda unit: unit.get(
                        document_path("hub_operations", self.f.owner, "bootstrap", BOOT)
                    )
                )
            )
