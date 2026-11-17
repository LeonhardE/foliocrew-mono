"""Exact static history proofs never retain a current source/read authorization."""

import copy
import socket
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from fixtures import OPERATION, OTHER_UID, SOURCE, UID, HoldingsFixture
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from test_authority_sync import projection
from test_firestore_store import MemoryRpc

from app._metadata_history import (
    _MetadataAttempt,
    _MetadataHistoryProofs,
    _own_authority,
    _OwnedAuthority,
)
from app.holdings import PortfolioError, PortfolioService, _authority
from app.lifecycle import state_path
from app.main import app
from app.store import FirestorePortfolioStore, SQLitePortfolioStore, StoreUnavailable, document_path
from folioview_shared.auth import require_google_user
from folioview_shared.encrypted.authority import RegistryCertificateMemo, verify_registry
from folioview_shared.encrypted.constants import (
    CONTRACT_VERSION,
    MAX_READ_BYTES,
    MAX_SAFE_INTEGER,
    MAX_STORED_DOCUMENT_BYTES,
)
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json
from folioview_shared.encrypted.reference_history import (
    REFERENCE_HISTORY_FORMAT,
    decode_reference_history,
)
from folioview_shared.identity import owner_key


def row(fixture, history, source=SOURCE):
    return {
        "version": 1,
        "ownerSubject": fixture.owner,
        "sourceId": source,
        "vaultId": fixture.vault,
        "rootJwk": copy.deepcopy(fixture.root_public),
        "rootKeyId": fixture.root_id,
        "registryHistory": copy.deepcopy(history),
        "resourceRef": {**fixture.resource, "resourceId": source},
        "sourceEpoch": 1,
        "active": True,
        "writerKeyIds": [fixture.kid("device_sig")],
        "recipientKeyIds": sorted([fixture.kid("device_enc"), fixture.kid("recovery_enc")]),
    }


class MetadataHistoryProofTests(unittest.TestCase):
    def setUp(self):
        # Both possible network paths fail before any real transport is used.
        self.addCleanup(patch.stopall)
        patch("socket.create_connection", side_effect=AssertionError("Network forbidden")).start()
        patch.object(
            socket.socket, "connect", side_effect=AssertionError("Network forbidden")
        ).start()
        self.f = HoldingsFixture()
        self.client = firestore.Client(
            project="synthetic-portfolio", database="portfolio", credentials=AnonymousCredentials()
        )
        self.addCleanup(self.client.close)
        self.rpc = MemoryRpc(self.client)
        self.client._firestore_api_internal = self.rpc
        self.store = FirestorePortfolioStore("synthetic-portfolio", "portfolio", client=self.client)
        self.now = 1000
        self.service = PortfolioService(self.store, clock=lambda: self.now)
        self.f.install(self.service)
        self.rpc.calls.clear()

    def name(self, source=SOURCE, owner=None):
        return self.client.document(
            document_path("portfolio_authorities", owner or self.f.owner, source)
        )._document_path

    def proof(self, memo, history=None, **changes):
        parameters = dict(
            root_jwk=self.f.root_public,
            root_key_id=self.f.root_id,
            owner=self.f.owner,
            vault=self.f.vault,
            now=self.now,
        )
        parameters.update(changes)
        return memo._verify([self.f.bundle] if history is None else history, **parameters)

    def test_two_http_equivalent_calls_still_read_current_rows_and_commit_zero_writes(self):
        with patch("app._metadata_history.verify_registry", wraps=verify_registry) as verify:
            first = self.service.metadata(UID, SOURCE)
            self.now += 1
            self.assertEqual(first, self.service.metadata(UID, SOURCE))
            self.assertEqual(verify.call_count, 1)
        self.assertEqual([kind for kind, _ in self.rpc.calls], ["begin", "get", "commit"] * 2)
        self.assertTrue(
            all(not kw["request"]["writes"] for kind, kw in self.rpc.calls if kind == "commit")
        )

    def test_actual_asgi_dependency_creates_fresh_services_but_reuses_only_process_proof(self):
        # Do NOT override get_service or the proof getter: use the real request
        # lifecycle, replacing only authenticated identity and the SDK RPC store.
        app.dependency_overrides[require_google_user] = lambda: SimpleNamespace(uid=UID)
        self.addCleanup(app.dependency_overrides.clear)
        created = []

        def service_for_request(*args, **kwargs):
            value = PortfolioService(*args, **kwargs)
            created.append(value)
            return value

        with (
            patch("app.api.get_store", return_value=self.store),
            patch("app.api.PortfolioService", side_effect=service_for_request),
            patch("app._metadata_history.verify_registry", wraps=verify_registry) as verify,
            TestClient(app) as http,
        ):
            url = f"/api/v2/holdings/sources/{SOURCE}"
            headers = {"X-FolioView-Contract": CONTRACT_VERSION}
            first = http.get(url, headers=headers)
            second = http.get(url, headers=headers)
            self.assertEqual((first.status_code, second.status_code), (200, 200))
            self.assertEqual(first.json(), second.json())
            self.assertEqual(verify.call_count, 1)
            self.assertEqual(len(created), 2)
            self.assertIsNot(created[0], created[1])
            self.rpc.documents[self.name()]["sourceEpoch"] = 2
            self.rpc.documents[self.name()]["version"] = 7
            changed = http.get(url, headers=headers)
            self.assertEqual(changed.status_code, 200)
            self.assertEqual(
                (changed.json()["sourceEpoch"], changed.json()["authorityVersion"]), (2, 7)
            )
            self.rpc.documents[self.name()]["active"] = False
            denied = http.get(url, headers=headers)
            self.assertEqual(denied.status_code, 403)
            self.assertEqual(denied.headers["cache-control"], "no-store")
            self.assertEqual(verify.call_count, 1)
            self.assertEqual(len(created), 4)
            self.assertEqual(len({id(value) for value in created}), 4)
        self.assertEqual(sum(kind == "get" for kind, _ in self.rpc.calls), 4)
        self.assertTrue(
            all(not kw["request"]["writes"] for kind, kw in self.rpc.calls if kind == "commit")
        )

    def test_reused_proof_keeps_strict_now_and_final_future_guard(self):
        memo = _MetadataHistoryProofs()
        with patch("app._metadata_history.verify_registry", wraps=verify_registry) as verify:
            registry = self.proof(memo)
            for bad in (True, -1, 1000.0, "1000", MAX_SAFE_INTEGER + 1):
                with self.subTest(now=bad), self.assertRaises(ContractError) as error:
                    self.proof(memo, now=bad)
                self.assertEqual(error.exception.code, "malformed_request")
            with self.assertRaises(ContractError) as error:
                self.proof(memo, now=registry.issued_at - 1)
            self.assertEqual(error.exception.code, "registry_conflict")
            self.assertEqual(verify.call_count, 1)

    def test_returned_registry_and_input_mutation_cannot_pollute_retained_proof(self):
        memo = _MetadataHistoryProofs()
        history = copy.deepcopy([self.f.bundle])
        first = self.proof(memo, history)
        first.__dict__["issued_at"] = -1
        first.__dict__["active_key_ids"] = frozenset()
        cert = self.proof(memo).cert(self.f.kid("device_sig"), now=1000)
        cert["expiresAt"] = 0
        self.assertIn(self.f.kid("device_sig"), self.proof(memo).active_key_ids)
        self.assertGreater(self.proof(memo).issued_at, 0)
        history[0]["checkpoint"]["signature"] = "A" * 86
        with self.assertRaises(ContractError):
            self.proof(memo, history)
        self.assertIn(self.f.kid("device_sig"), self.proof(memo).active_key_ids)
        self.assertFalse(hasattr(memo, "put"))
        with self.assertRaises(AttributeError):
            memo.entries = {}

    def test_whole_history_root_and_identity_misses_never_accept_prior_proof(self):
        memo = _MetadataHistoryProofs()
        self.proof(memo)
        other = HoldingsFixture()
        for changes in (
            {"root_jwk": other.root_public, "root_key_id": other.root_id},
            {"root_jwk": self.f.root_public | {"extra": "same-thumbprint-invalid-root"}},
            {"owner": owner_key(OTHER_UID)},
            {"vault": "other_vault"},
        ):
            with self.subTest(changes=tuple(changes)), self.assertRaises(ContractError):
                self.proof(memo, **changes)
        tampered = copy.deepcopy(self.f.bundle)
        tampered["entries"][0]["active"] = not tampered["entries"][0]["active"]
        with self.assertRaises(ContractError):
            self.proof(memo, [tampered])
        malformed = copy.deepcopy(self.f.bundle)
        malformed["checkpoint"]["signature"] = "A" * 86
        with patch("app._metadata_history.verify_registry", wraps=verify_registry) as verify:
            for _ in range(2):
                with self.assertRaises(ContractError):
                    self.proof(memo, [self.f.bundle, malformed])
            self.assertEqual(verify.call_count, 4)  # A valid prefix cannot publish a bad suffix.

    def test_cache_has_no_time_observer_but_current_time_and_capacity_stay_live(self):
        memo = _MetadataHistoryProofs()
        with (
            patch("time.monotonic", side_effect=AssertionError("No cache clock")),
            patch("app._metadata_history.verify_registry", wraps=verify_registry) as verify,
        ):
            self.proof(memo)
            self.proof(memo, now=MAX_SAFE_INTEGER)
            self.proof(memo, now=1001)
            self.assertEqual(verify.call_count, 1)
            with self.assertRaises(ContractError):
                self.proof(memo, now=self.f.registry.issued_at - 1)
        with patch("app._metadata_history._MAX_LOGICAL_BYTES", 1):
            memo = _MetadataHistoryProofs()
            with patch("app._metadata_history.verify_registry", wraps=verify_registry) as verify:
                self.proof(memo)
                self.proof(memo)
                self.assertEqual(verify.call_count, 2)

    def test_new_signed_bytes_and_revoked_successor_require_whole_history_validation(self):
        memo = _MetadataHistoryProofs()
        with patch("app._metadata_history.verify_registry", wraps=verify_registry) as verify:
            self.proof(memo)
            resigned = self.f.make_bundle()
            self.assertNotEqual(canonical_json(self.f.bundle), canonical_json(resigned))
            self.assertEqual(
                self.proof(memo, [resigned]).checkpoint_digest, self.f.registry.checkpoint_digest
            )
            self.assertEqual(verify.call_count, 2)
            successor = self.f.make_bundle(previous=self.f.registry, revoked=("device_sig",))
            revoked = self.proof(memo, [self.f.bundle, successor])
            self.assertEqual(verify.call_count, 4)
            with self.assertRaises(ContractError):
                revoked.cert(self.f.kid("device_sig"), role="device_sig", now=1000)
        self.service.metadata(UID, SOURCE)
        self.rpc.documents[self.name()]["registryHistory"] = canonical_json(
            [self.f.bundle, successor]
        )
        self.assertEqual(self.service.metadata(UID, SOURCE)["state"], "active")
        with self.assertRaises(ContractError):
            self.f.write(self.service)

    def test_entry_eviction_does_not_reject_valid_histories(self):
        memo = _MetadataHistoryProofs()
        fixtures = [self.f] + [HoldingsFixture() for _ in range(8)]

        def resolve(fixture):
            return memo._verify(
                [fixture.bundle],
                root_jwk=fixture.root_public,
                root_key_id=fixture.root_id,
                owner=fixture.owner,
                vault=fixture.vault,
                now=1000,
            )

        with patch("app._metadata_history.verify_registry", wraps=verify_registry) as verify:
            for fixture in fixtures:
                resolve(fixture)
            self.assertEqual(verify.call_count, 9)
            resolve(fixtures[-1])
            self.assertEqual(verify.call_count, 9)
            resolve(fixtures[0])
            self.assertEqual(verify.call_count, 10)

    def test_owned_input_is_sealed_cloned_single_use_and_cannot_inject_a_registry(self):
        memo = _MetadataHistoryProofs()
        for cls in (_OwnedAuthority, _MetadataAttempt):
            with self.subTest(cls=cls.__name__), self.assertRaises(TypeError):
                cls()
        fake = object.__new__(_OwnedAuthority)
        object.__setattr__(fake, "_OwnedAuthority__seal", object())
        with self.assertRaises(ContractError):
            memo._resolve(fake, 1000)
        with self.assertRaises(ContractError):
            memo._resolve(self.f.registry, 1000)
        fake_attempt = object.__new__(_MetadataAttempt)
        with self.assertRaises(ContractError):
            fake_attempt._resolve(memo, fake, 1000)

        external = row(self.f, [self.f.bundle])
        owned = _own_authority(external)
        self.assertFalse(hasattr(owned, "document"))
        self.assertFalse(hasattr(owned, "row"))

        def mutate_external(bundle, **kwargs):
            external["registryHistory"][0]["checkpoint"]["signature"] = "A" * 86
            external["rootJwk"]["x"] = "A" * 43
            self.assertIsNot(bundle, external["registryHistory"][0])
            return verify_registry(bundle, **kwargs)

        with patch("app._metadata_history.verify_registry", side_effect=mutate_external):
            accepted = owned._authorize(self.f.owner, SOURCE, 1000, memo, memo._attempt())
        self.assertEqual(accepted.registry.checkpoint_digest, self.f.registry.checkpoint_digest)
        accepted.document["rootJwk"]["x"] = "A" * 43
        accepted.document["registryHistory"][0]["checkpoint"]["signature"] = "A" * 86
        with self.assertRaises(ContractError):
            owned._authorize(self.f.owner, SOURCE, 1000, memo, memo._attempt())
        self.assertEqual(self.proof(memo).checkpoint_digest, self.f.registry.checkpoint_digest)
        # No caller-controlled mapping can preload the metadata attempt cache.
        owned = _own_authority(row(self.f, [self.f.bundle]))
        with self.assertRaises(ContractError):
            owned._authorize(self.f.owner, SOURCE, 1000, memo, {"fake": self.f.registry})

    def test_threads_share_only_detached_successful_proofs(self):
        memo = _MetadataHistoryProofs()
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: self.proof(memo), range(12)))
        self.assertEqual(len({id(value) for value in results}), 12)
        self.assertTrue(
            all(value.checkpoint_digest == self.f.registry.checkpoint_digest for value in results)
        )
        results[0].__dict__["issued_at"] = -1
        self.assertGreater(self.proof(memo).issued_at, 0)
        fixtures = [HoldingsFixture() for _ in range(9)]

        def other(fixture):
            return memo._verify(
                [fixture.bundle],
                root_jwk=fixture.root_public,
                root_key_id=fixture.root_id,
                owner=fixture.owner,
                vault=fixture.vault,
                now=1000,
            )

        with ThreadPoolExecutor(max_workers=4) as executor:
            values = list(executor.map(other, fixtures))
        self.assertEqual(len(values), 9)
        retained = memo._MetadataHistoryProofs__entries
        self.assertLessEqual(len(retained), 8)
        self.assertEqual(
            sum(entry.weight for entry in retained.values()),
            memo._MetadataHistoryProofs__size,
        )
        self.assertLessEqual(memo._MetadataHistoryProofs__size, 4 * 1024 * 1024)

    def test_current_rows_heads_lifecycle_and_storage_remain_fresh(self):
        expected = self.service.metadata(UID, SOURCE)
        original = copy.deepcopy(self.rpc.documents)
        head_name = self.client.document(
            document_path("portfolio_heads", self.f.owner, SOURCE)
        )._document_path

        def corrupt_head():
            self.rpc.documents[head_name] = {
                "ownerSubject": owner_key(OTHER_UID),
                "sourceId": SOURCE,
                "revision": 1,
                "snapshotId": "synthetic_snapshot",
            }

        for mutate in (
            corrupt_head,
            lambda: self.rpc.documents[self.name()].update(active=False),
            lambda: self.rpc.documents[self.name()].update(sourceEpoch=True),
            lambda: self.rpc.documents[self.name()].update(ownerSubject=owner_key(OTHER_UID)),
            lambda: self.rpc.documents[self.name()].update(
                rootJwk=self.f.root_public | {"extra": "bad"}
            ),
            lambda: self.rpc.documents[self.name()].update(
                registryHistory=b" " + self.rpc.documents[self.name()]["registryHistory"]
            ),
        ):
            self.rpc.documents = copy.deepcopy(original)
            mutate()
            with self.assertRaises((StoreUnavailable, PortfolioError)):
                self.service.metadata(UID, SOURCE)
        self.rpc.documents = copy.deepcopy(original)
        path = self.client.document(state_path(self.f.owner, SOURCE))._document_path
        self.rpc.documents[path] = {
            "ownerSubject": self.f.owner,
            "sourceId": SOURCE,
            "resourceRef": self.f.resource,
            "sourceEpoch": 1,
            "state": "revoking",
            "mutationCount": 1,
            "pendingMutationId": "synthetic_mutation_000001",
            "lastMutationId": "synthetic_mutation_000001",
        }
        self.assertEqual(self.service.metadata(UID, SOURCE)["state"], "revoking")
        self.rpc.documents = copy.deepcopy(original)
        self.rpc.documents[self.name()]["version"] = 7
        self.rpc.documents[self.name()]["sourceEpoch"] = 2
        current = self.service.metadata(UID, SOURCE)
        self.assertEqual((current["authorityVersion"], current["sourceEpoch"]), (7, 2))
        self.assertEqual(expected["snapshotId"], current["snapshotId"])

    def test_aborted_retry_rereads_new_authorization_clock_and_history(self):
        self.service.metadata(UID, SOURCE)
        for change in ("inactive", "future", "bad_history"):
            original = copy.deepcopy(self.rpc.documents)
            self.rpc.calls.clear()
            self.now = 1000

            def mutate(change=change):
                if change == "inactive":
                    self.rpc.documents[self.name()]["active"] = False
                elif change == "future":
                    self.now = 0
                else:
                    self.rpc.documents[self.name()]["registryHistory"] = canonical_json(
                        [self.f.bundle | {"unexpected": True}]
                    )

            self.rpc.aborts, self.rpc.before_abort = 1, mutate
            with self.assertRaises((StoreUnavailable, PortfolioError)):
                self.service.metadata(UID, SOURCE)
            self.assertEqual(sum(kind == "get" for kind, _ in self.rpc.calls), 2)
            self.assertTrue(
                all(not kw["request"]["writes"] for kind, kw in self.rpc.calls if kind == "commit")
            )
            self.rpc.documents = original
        self.now = 1000

    def test_write_install_snapshot_do_not_borrow_proofs_but_fresh_services_share_static_evidence(
        self,
    ):
        self.service.metadata(UID, SOURCE)
        with patch("app.holdings.verify_registry", wraps=verify_registry) as original:
            self.f.write(self.service)
            self.assertGreater(original.call_count, 0)
            count = original.call_count
            self.service.snapshot(UID, SOURCE)
            self.assertGreater(original.call_count, count)
            count = original.call_count
            self.service.receipt(UID, SOURCE, OPERATION)
            self.assertGreater(original.call_count, count)
            count = original.call_count
            self.f.install(self.service, version=1)
            self.assertGreater(original.call_count, count)
            count = original.call_count
            self.service.synchronize_authority(UID, SOURCE, projection(self.f))
            self.assertGreater(original.call_count, count)
        other_service = PortfolioService(self.store, clock=lambda: 1000)
        with patch("app._metadata_history.verify_registry", wraps=verify_registry) as verify:
            other_service.metadata(UID, SOURCE)
            self.assertEqual(verify.call_count, 0)

    def test_metadata_expiry_semantics_and_default_authority_path_remain_unchanged(self):
        metadata = self.service.metadata(UID, SOURCE)
        self.now = max(cert["expiresAt"] for cert in self.f.certificates.values()) + 1
        self.assertEqual(metadata, self.service.metadata(UID, SOURCE))
        with self.assertRaises(ContractError):
            self.f.write(self.service)
        document = row(self.f, [self.f.bundle])
        with patch("app.holdings.verify_registry", wraps=verify_registry) as verify:
            _authority(document, self.f.owner, SOURCE, self.now)
            _authority(document, self.f.owner, SOURCE, self.now)
            self.assertEqual(verify.call_count, 2)


class LargeMetadataHistoryProofTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        patch("socket.create_connection", side_effect=AssertionError("Network forbidden")).start()
        patch.object(
            socket.socket, "connect", side_effect=AssertionError("Network forbidden")
        ).start()

    @classmethod
    def setUpClass(cls):
        f = HoldingsFixture()
        f.certificates = {
            name: value for name, value in f.certificates.items() if not name.startswith("A")
        }
        f.bundle = f.make_bundle()
        f.registry = f.verify(f.bundle)
        history = [f.bundle]
        previous = f.registry
        histories = {}
        signatures = RegistryCertificateMemo()
        for generation in range(2, 26):
            for suffix, role in (("sig", "agent_sig"), ("enc", "agent_enc")):
                f.add_key(
                    f"history_{generation:032x}_{suffix}",
                    role,
                    f"agent_{generation:032x}",
                    f"connection_{generation:032x}",
                )
            revoked = (f"history_{2:032x}_sig", f"history_{2:032x}_enc") if generation >= 24 else ()
            bundle = f.make_bundle(previous=previous, revoked=revoked)
            known = {
                entry["certificate"]["payload"]: entry["certificate"]
                for entry in history[-1]["entries"]
            }
            for entry in bundle["entries"]:
                entry["certificate"] = copy.deepcopy(
                    known.get(entry["certificate"]["payload"], entry["certificate"])
                )
            previous = f.verify(bundle, previous=previous, signature_memo=signatures)
            history.append(bundle)
            if generation in (24, 25):
                histories[generation] = copy.deepcopy(history)
        cls.fixture, cls.histories = f, histories

    def test_real_24_25_generations_sqlite_and_sdk_keep_budgets_dtos_and_fresh_reads(self):
        f = self.fixture
        sources = [SOURCE, "holdings_B", "holdings_C"]
        documents = [
            row(f, self.histories[generation], source)
            for source, generation in zip(sources, (24, 25, 25), strict=True)
        ]
        for document in documents:
            self.assertGreater(len(canonical_json(document)), MAX_STORED_DOCUMENT_BYTES)
            self.assertLessEqual(len(canonical_json(document)), MAX_READ_BYTES)
        with tempfile.TemporaryDirectory() as directory:
            sqlite = SQLitePortfolioStore(Path(directory) / "portfolio.sqlite")
            client = firestore.Client(
                project="synthetic-portfolio",
                database="portfolio",
                credentials=AnonymousCredentials(),
            )
            self.addCleanup(client.close)
            rpc = MemoryRpc(client)
            client._firestore_api_internal = rpc
            firestore_store = FirestorePortfolioStore(
                "synthetic-portfolio", "portfolio", client=client
            )
            results = []
            for store in (sqlite, firestore_store):
                for document in documents:
                    path = document_path("portfolio_authorities", f.owner, document["sourceId"])
                    store.transact(
                        lambda unit, path=path, document=document: unit.put(path, document)
                    )
                service = PortfolioService(store, clock=lambda: 1000)
                rpc.calls.clear()
                with patch(
                    "app._metadata_history.verify_registry", wraps=verify_registry
                ) as verify:
                    first = service.metadata_many(UID, sources)
                    expected_calls = 49 if store is sqlite else 0
                    self.assertEqual(verify.call_count, expected_calls)
                    self.assertEqual(
                        PortfolioService(store, clock=lambda: 1000).metadata_many(UID, sources),
                        first,
                    )
                    self.assertEqual(verify.call_count, expected_calls)
                results.append(canonical_json(first))
            self.assertEqual(results[0], results[1])
            self.assertEqual(sum(kind == "get" for kind, _ in rpc.calls), 2)
            self.assertTrue(
                all(not kw["request"]["writes"] for kind, kw in rpc.calls if kind == "commit")
            )
            from folioview_shared.encrypted.jsonutil import strict_json_loads

            for document in rpc.documents.values():
                self.assertLessEqual(
                    len(
                        canonical_json(
                            {
                                **document,
                                "registryHistory": strict_json_loads(document["registryHistory"]),
                            }
                        )
                    ),
                    MAX_STORED_DOCUMENT_BYTES,
                )
                compact = strict_json_loads(document["registryHistory"])
                self.assertEqual(compact["format"], REFERENCE_HISTORY_FORMAT)
                self.assertIn(len(decode_reference_history(document["registryHistory"])), (24, 25))
