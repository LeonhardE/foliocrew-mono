"""Current-time authorization on actual SDK retries, using synthetic keys only."""

import copy
import unittest
from unittest.mock import patch

import test_private_display_name_store as name_fixture
from fixtures import BOOT, SOURCE, UID
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from test_firestore_store import MemoryRpc

from app.private_display_names import PrivateDisplayNameService
from app.store import FirestoreHubStore, StoreUnavailable
from app.vaults import VaultService
from folioview_shared.encrypted.constants import MAX_SAFE_INTEGER
from folioview_shared.encrypted.errors import ContractError


class DisplayNameRetryTimeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = name_fixture.DisplayNameStoreTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.client = firestore.Client(
            project="synthetic-hub", database="agent-hub", credentials=AnonymousCredentials()
        )
        self.addCleanup(self.client.close)
        self.rpc = MemoryRpc(self.client)
        self.client._firestore_api_internal = self.rpc
        self.store = FirestoreHubStore("synthetic-hub", "agent-hub", client=self.client)
        vaults = VaultService(self.store, clock=lambda: self.fixture.now)
        vaults.bootstrap(UID, self.fixture.f.bootstrap(), BOOT)
        vaults.create_source(
            UID,
            self.fixture.f.vault,
            SOURCE,
            self.fixture.f.control(),
            "synthetic_source_create_0001",
            self.fixture.f.kid("device_sig"),
        )
        self.names = PrivateDisplayNameService(self.store, clock=lambda: self.fixture.now)
        self.rpc.calls.clear()

    def abort_and_advance(self, now):
        def advance():
            self.fixture.now = now

        self.rpc.aborts, self.rpc.before_abort = 1, advance

    def write(self, packet):
        return self.names.write(UID, self.fixture.f.vault, SOURCE, *packet)

    def commits(self):
        return [args for kind, args in self.rpc.calls if kind == "commit"]

    def test_uncommitted_retry_rechecks_signer_expiry_without_alias_or_receipt(self):
        expiry = self.fixture.f.certificates["device_sig"]["expiresAt"]
        self.fixture.now = expiry - 1
        packet = self.fixture.packet()
        before = copy.deepcopy(self.rpc.documents)
        self.abort_and_advance(expiry + 1)
        with self.assertRaises(ContractError) as error:
            self.write(packet)
        self.assertEqual("key_authorization_required", error.exception.code)
        self.assertEqual(before, self.rpc.documents)
        self.assertEqual([2], [len(c["request"]["writes"]) for c in self.commits()])

    def test_uncommitted_retry_rechecks_signed_control_age(self):
        packet = self.fixture.packet()
        self.fixture.now = 1299
        before = copy.deepcopy(self.rpc.documents)
        self.abort_and_advance(1301)
        with self.assertRaises(ContractError) as error:
            self.write(packet)
        self.assertEqual("key_authorization_required", error.exception.code)
        self.assertEqual(before, self.rpc.documents)
        self.assertEqual([2], [len(c["request"]["writes"]) for c in self.commits()])

    def test_accepted_at_uses_successful_attempt_clock(self):
        packet = self.fixture.packet()
        self.abort_and_advance(1002)
        saved = self.write(packet)
        self.assertEqual(1002, saved["item"]["state"]["acceptedAt"])
        self.assertEqual([2, 2], [len(c["request"]["writes"]) for c in self.commits()])

    def test_committed_original_replay_survives_retry_across_signer_expiry(self):
        expiry = self.fixture.f.certificates["device_sig"]["expiresAt"]
        self.fixture.now = expiry - 1
        packet = self.fixture.packet()
        saved = self.write(packet)
        before = copy.deepcopy(self.rpc.documents)
        self.rpc.calls.clear()
        self.abort_and_advance(expiry + 1)
        self.assertEqual(saved, self.write(packet))
        self.assertEqual(expiry - 1, saved["item"]["state"]["acceptedAt"])
        self.assertEqual(before, self.rpc.documents)
        self.assertEqual([0, 0], [len(c["request"]["writes"]) for c in self.commits()])

    def test_read_and_listing_retry_recheck_time_even_with_static_history_hit(self):
        self.write(self.fixture.packet())
        self.assertTrue(self.names.registry_cache)
        checkpoint_time = self.fixture.f.registry.issued_at
        for method in ("read", "listing"):
            with self.subTest(method=method):
                self.fixture.now = checkpoint_time
                self.rpc.calls.clear()
                before = copy.deepcopy(self.rpc.documents)
                self.abort_and_advance(checkpoint_time - 1)
                with self.assertRaises(ContractError) as error:
                    if method == "read":
                        self.names.read(UID, self.fixture.f.vault, SOURCE)
                    else:
                        self.names.listing(UID, self.fixture.f.vault)
                self.assertEqual("registry_conflict", error.exception.code)
                self.assertEqual(before, self.rpc.documents)
                self.assertEqual([0], [len(c["request"]["writes"]) for c in self.commits()])

    def test_sqlite_transaction_wait_does_not_freeze_new_write_time(self):
        fixture = self.fixture
        expiry = fixture.f.certificates["device_sig"]["expiresAt"]
        fixture.now = expiry - 1
        packet = fixture.packet()
        original = fixture.store.transact

        def delayed_start(callback):
            fixture.now = expiry + 1
            return original(callback)

        with patch.object(fixture.store, "transact", side_effect=delayed_start):
            with self.assertRaises(ContractError) as error:
                fixture.write(packet)
        self.assertEqual("key_authorization_required", error.exception.code)
        self.assertIsNone(fixture.service.read(UID, fixture.f.vault, SOURCE)["item"])
        with self.assertRaises(ContractError) as error:
            fixture.service.read(UID, fixture.f.vault, SOURCE, packet[1])
        self.assertEqual("not_found", error.exception.code)

    def test_clock_failures_are_closed_and_valid_fractional_clock_is_floored(self):
        for value in (True, "1000", -1, float("nan"), float("inf"), MAX_SAFE_INTEGER + 1):
            with self.subTest(value=value):
                names = PrivateDisplayNameService(self.store, clock=lambda v=value: v)
                with self.assertRaises(StoreUnavailable):
                    names.listing(UID, self.fixture.f.vault)
        names = PrivateDisplayNameService(self.store, clock=lambda: 1000.9)
        self.assertEqual(1000, names.now())
