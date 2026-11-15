"""Actual SDK retry-time checks for synthetic public-authority installation."""

import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from fixtures import OPERATION, SOURCE, UID, HoldingsFixture
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from test_authority_sync import DELEGATION, projection
from test_firestore_store import MemoryRpc

from app.api import get_service
from app.authority_sync import get_authority_client
from app.holdings import PortfolioService
from app.main import app
from app.store import FirestorePortfolioStore, SQLitePortfolioStore, document_path
from folioview_shared.auth import require_google_user
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError


class AuthorityRetryTimeTests(unittest.TestCase):
    def setUp(self):
        self.client = firestore.Client(
            project="synthetic-portfolio",
            database="portfolio",
            credentials=AnonymousCredentials(),
        )
        self.addCleanup(self.client.close)
        self.rpc = MemoryRpc(self.client)
        self.client._firestore_api_internal = self.rpc
        self.store = FirestorePortfolioStore("synthetic-portfolio", "portfolio", client=self.client)
        self.now = 1000
        self.service = PortfolioService(self.store, clock=lambda: self.now)
        self.f = HoldingsFixture()
        self.expire_at(1001)

    def expire_at(self, expiry):
        for certificate in self.f.certificates.values():
            certificate["expiresAt"] = expiry
        self.f.bundle = self.f.make_bundle()
        self.f.registry = self.f.verify(self.f.bundle)

    def reset(self):
        self.now = 1000
        self.rpc.documents.clear()
        self.rpc.calls.clear()
        self.rpc.aborts, self.rpc.before_abort = 0, None

    def install(self, method, *, service=None, active=True):
        service = self.service if service is None else service
        if method == "internal":
            return self.f.install(service, active=active)
        return service.synchronize_authority(UID, SOURCE, {**projection(self.f), "active": active})

    def abort_and_advance(self, now):
        def advance():
            self.now = now

        self.rpc.aborts, self.rpc.before_abort = 1, advance

    def commits(self):
        return [len(args["request"]["writes"]) for kind, args in self.rpc.calls if kind == "commit"]

    def attempts(self):
        return sum(kind == "begin" for kind, _ in self.rpc.calls)

    def test_both_adapters_reject_uncommitted_retry_after_selected_keys_expire(self):
        for method in ("internal", "sync"):
            with self.subTest(method=method):
                self.reset()
                self.abort_and_advance(1002)
                with self.assertRaises(ContractError) as error:
                    self.install(method)
                self.assertEqual("key_authorization_required", error.exception.code)
                self.assertEqual(2, self.attempts())
                self.assertEqual([1], self.commits())
                self.assertEqual({}, self.rpc.documents)
                self.assertTrue(any(kind == "rollback" for kind, _ in self.rpc.calls))

    def test_fresh_expired_adapters_reject_in_first_attempt_without_writes(self):
        for method in ("internal", "sync"):
            with self.subTest(method=method):
                self.reset()
                self.now = 1002
                with self.assertRaises(ContractError) as error:
                    self.install(method)
                self.assertEqual("key_authorization_required", error.exception.code)
                self.assertEqual(1, self.attempts())
                self.assertEqual([], self.commits())
                self.assertEqual({}, self.rpc.documents)

    def test_both_adapters_preserve_successful_nonexpired_retry(self):
        self.expire_at(1005)
        for method in ("internal", "sync"):
            with self.subTest(method=method):
                self.reset()
                self.abort_and_advance(1002)
                result = self.install(method)
                self.assertEqual(1, result if method == "internal" else result["authorityVersion"])
                self.assertEqual(2, self.attempts())
                self.assertEqual([1, 1], self.commits())
                self.assertEqual(1, len(self.rpc.documents))
                self.assertEqual(1, self.service.metadata(UID, SOURCE)["authorityVersion"])

    def test_both_adapters_recheck_full_registry_after_clock_rollback(self):
        for method in ("internal", "sync"):
            with self.subTest(method=method):
                self.reset()
                self.abort_and_advance(self.f.registry.issued_at - 1)
                with self.assertRaises(ContractError) as error:
                    self.install(method)
                self.assertEqual("registry_conflict", error.exception.code)
                self.assertEqual(2, self.attempts())
                self.assertEqual([1], self.commits())
                self.assertEqual({}, self.rpc.documents)

    def test_inactive_fencing_replicas_still_accept_revoked_expired_keys(self):
        self.f.bundle = self.f.make_bundle(revoked=("device_sig", "device_enc"))
        self.f.registry = self.f.verify(self.f.bundle)
        for method in ("internal", "sync"):
            with self.subTest(method=method):
                self.reset()
                self.abort_and_advance(1002)
                self.install(method, active=False)
                self.assertEqual([1, 1], self.commits())
                row = self.store.transact(
                    lambda unit: unit.get(
                        document_path("portfolio_authorities", self.f.owner, SOURCE)
                    )
                )
                self.assertIs(row["active"], False)
                self.assertEqual(self.f.kid("device_sig"), row["writerKeyIds"][0])

    def test_sync_noop_retry_still_checks_current_key_eligibility(self):
        self.install("sync")
        before = copy.deepcopy(self.rpc.documents)
        self.rpc.calls.clear()
        self.abort_and_advance(1002)
        with self.assertRaises(ContractError) as error:
            self.install("sync")
        self.assertEqual("key_authorization_required", error.exception.code)
        self.assertEqual(2, self.attempts())
        self.assertEqual([0], self.commits())
        self.assertEqual(before, self.rpc.documents)

    def test_sync_retry_rereads_root_epoch_and_locked_state_without_overwriting(self):
        self.expire_at(5000)
        other = HoldingsFixture()
        for change, code in (
            (projection(other), "recipient_binding_mismatch"),
            ({"sourceEpoch": 2}, "recipient_binding_mismatch"),
            ({"active": False}, "insufficient_scope"),
        ):
            with self.subTest(change=tuple(change)):
                self.reset()
                self.install("sync")
                name = next(iter(self.rpc.documents))
                self.rpc.calls.clear()
                winner = {}

                def win(change=change, name=name, winner=winner):
                    self.rpc.documents[name].update(copy.deepcopy(change))
                    winner.update(copy.deepcopy(self.rpc.documents))

                self.rpc.aborts, self.rpc.before_abort = 1, win
                with self.assertRaises(ContractError) as error:
                    self.install("sync")
                self.assertEqual(code, error.exception.code)
                self.assertEqual(winner, self.rpc.documents)
                self.assertEqual([0], self.commits())

    def test_internal_retry_preserves_current_version_cas(self):
        self.expire_at(5000)
        self.install("internal")
        name = next(iter(self.rpc.documents))
        self.rpc.calls.clear()
        winner = {}

        def win():
            self.rpc.documents[name]["version"] = 3
            winner.update(copy.deepcopy(self.rpc.documents))

        self.rpc.aborts, self.rpc.before_abort = 1, win
        with self.assertRaises(ContractError) as error:
            self.f.install(self.service, version=1)
        self.assertEqual("version_conflict", error.exception.code)
        self.assertEqual(winner, self.rpc.documents)
        self.assertEqual([1], self.commits())

    def test_asgi_sync_retry_refuses_expired_selection_with_fixed_error_and_no_store(self):
        document = projection(self.f)

        class FixedVerifiedHub:
            def read(self, uid, source, delegation):
                if (uid, source, delegation) != (UID, SOURCE, DELEGATION):
                    raise AssertionError("Wrong delegated synthetic owner")
                return copy.deepcopy(document)

        app.dependency_overrides[get_service] = lambda: self.service
        app.dependency_overrides[require_google_user] = lambda: SimpleNamespace(uid=UID)
        app.dependency_overrides[get_authority_client] = FixedVerifiedHub
        self.abort_and_advance(1002)
        try:
            with TestClient(app) as http:
                response = http.post(
                    f"/api/v2/holdings/sources/{SOURCE}/authority-sync",
                    headers={
                        "X-FolioView-Contract": CONTRACT_VERSION,
                        "X-FolioView-Authority-Delegation": DELEGATION,
                    },
                    json={"contractVersion": CONTRACT_VERSION},
                )
        finally:
            app.dependency_overrides.clear()
        self.assertEqual(403, response.status_code)
        self.assertEqual("key_authorization_required", response.json()["error"]["code"])
        self.assertEqual("no-store", response.headers["cache-control"])
        self.assertEqual(2, self.attempts())
        self.assertEqual([1], self.commits())
        self.assertEqual({}, self.rpc.documents)

    def test_private_snapshot_retry_remains_closed_and_old_receipts_remain_readable(self):
        self.install("internal")
        saved = self.f.write(self.service)
        before = copy.deepcopy(self.rpc.documents)
        self.rpc.calls.clear()
        self.abort_and_advance(1002)
        with self.assertRaises(ContractError) as error:
            self.f.write(
                self.service, snapshot="snapshot_2", revision=2, operation=OPERATION + "_next"
            )
        self.assertEqual("key_authorization_required", error.exception.code)
        self.assertEqual(before, self.rpc.documents)
        self.assertEqual([3], self.commits())
        self.assertEqual(saved, self.service.receipt(UID, SOURCE, OPERATION))
        self.assertEqual(saved, self.service.snapshot(UID, SOURCE)["receipt"])

    def test_sqlite_transaction_wait_rechecks_both_adapters(self):
        for method in ("internal", "sync"):
            with self.subTest(method=method), tempfile.TemporaryDirectory() as directory:
                self.now = 1000
                store = SQLitePortfolioStore(Path(directory) / "portfolio.sqlite3")
                service = PortfolioService(store, clock=lambda: self.now)
                transact = store.transact

                def delayed_start(callback, transact=transact):
                    self.now = 1002
                    return transact(callback)

                with patch.object(store, "transact", side_effect=delayed_start):
                    with self.assertRaises(ContractError) as error:
                        self.install(method, service=service)
                self.assertEqual("key_authorization_required", error.exception.code)
                self.assertIsNone(
                    store.transact(
                        lambda unit: unit.get(
                            document_path("portfolio_authorities", self.f.owner, SOURCE)
                        )
                    )
                )
