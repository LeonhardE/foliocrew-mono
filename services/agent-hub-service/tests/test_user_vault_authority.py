"""A Hub lookup keeps the signed User epoch bound to its exact transferred writer."""

import asyncio
import copy
import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import anyio
import httpx
from fixtures import BOOT, UID
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from test_firestore_store import MemoryRpc
from test_tasks import TaskFixture

from app import tasks
from app.catalogue import CatalogueService, item
from app.store import (
    FirestoreHubStore,
    SQLiteHubStore,
    StoreUnavailable,
    private_resource_writer_fence_path,
)
from app.task_overview import TaskOverviewService
from app.user_vault_authority import HUB_AUTHORITY_PATH, ScopedUserVaults, UserVaultAuthority
from app.vaults import VaultService
from folioview_shared.delegation import PRIVATE_AUTHORITY_DELEGATION_TYPE
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import signing_input_fingerprint
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json, strict_json_loads
from folioview_shared.encrypted.private_resources import PrivateRegistryCursor, source_index_digest


class UserVaultAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.f = f = TaskFixture()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = SQLiteHubStore(Path(folder.name) / "hub.sqlite3")
        self.issuer = "https://agent-hub-api-123456789.us-central1.run.app"
        self.user_origin = "https://user-api-123456789.us-central1.run.app"
        self.caller = "synthetic-hub@synthetic-project.iam.gserviceaccount.com"
        self.signer = Mock()
        self.signer.sign.return_value = "signed.owner.delegation"
        self.wire = Mock(side_effect=self.reply)
        self.client = UserVaultAuthority(
            issuer=self.issuer,
            caller=self.caller,
            user_origin=self.user_origin,
            signer_factory=lambda: self.signer,
            token_factory=lambda *_a, **_kw: "google.workload.identity",
            transport=httpx.MockTransport(self.wire),
            wall_clock=lambda: 1000,
        )
        original = f.registry
        first = f.make_bundle(previous=original, issued_at=900)
        start = f.verify(first, previous=original)
        final_bundle = f.make_bundle(previous=start, issued_at=950)
        final = f.verify(final_bundle, previous=start)
        initial = PrivateRegistryCursor(start, 2).head()
        archive = {"state": "active", "digest": "a" * 64, "version": 1}
        change = f.sign(
            {
                "contractVersion": CONTRACT_VERSION,
                "profile": "folioview.owner-registry-transition.v1",
                "ownerSubject": f.owner,
                "vaultId": f.vault,
                "rootKeyId": f.root_id,
                "operationId": "synthetic_hub_registry_transfer_01",
                "previousVaultVersion": 1,
                "nextVaultVersion": 2,
                "previousHead": PrivateRegistryCursor(original, 1).head(),
                "nextHead": initial,
                "archive": archive,
                "issuedAt": 900,
                "ownerKeyIds": sorted(start.active_key_ids),
            },
            "root",
        )
        self.fence = {
            "ownerSubject": f.owner,
            "vaultId": f.vault,
            "state": "transferred",
            "writerEpoch": 2,
            "rootKeyId": f.root_id,
            "transitionFingerprint": signing_input_fingerprint(change),
        }
        self.authority = {
            "ownerSubject": f.owner,
            "vaultId": f.vault,
            "rootKeyId": f.root_id,
            "rootJwk": f.root_public,
            "vaultVersion": 3,
            "registry": PrivateRegistryCursor(final, 2).head(),
            "registryStart": initial,
            "archive": archive,
            "signedTransition": change,
            "sourcesDigest": source_index_digest([]),
            "registryHistory": [first, final_bundle],
            "sources": [],
        }

    def reply(self, request):
        self.assertEqual(str(request.url), self.user_origin + HUB_AUTHORITY_PATH)
        self.assertEqual(request.headers["authorization"], "Bearer google.workload.identity")
        self.assertEqual(request.headers["x-folioview-delegation"], "signed.owner.delegation")
        value = strict_json_loads(request.content)
        self.assertEqual((value["consumer"], value["sourceId"]), ("hub", None))
        self.assertEqual((value["ownerSubject"], value["vaultId"]), (self.f.owner, self.f.vault))
        claims = self.signer.sign.call_args.args[0]
        self.assertEqual(
            self.signer.sign.call_args.kwargs["typ"], PRIVATE_AUTHORITY_DELEGATION_TYPE
        )
        self.assertEqual(claims["aud"], str(request.url))
        self.assertEqual(
            (claims["sub"], claims["caller"], claims["jti"]), (UID, self.caller, value["nonce"])
        )
        self.assertEqual(claims["requestDigest"], hashlib.sha256(request.content).hexdigest())
        return httpx.Response(
            200,
            headers={"X-FolioView-Contract": CONTRACT_VERSION, "Content-Type": "application/json"},
            content=canonical_json(
                {
                    **{
                        key: value[key]
                        for key in ("contractVersion", "profile", "consumer", "nonce")
                    },
                    "requestDigest": claims["requestDigest"],
                    "authority": self.authority,
                }
            ),
        )

    def test_verifies_current_user_epoch_and_rechecks_the_local_transfer(self):
        read = self.client.read(UID, self.f.vault, self.fence)
        self.assertEqual(read.cursor.head(), self.authority["registry"])
        path = private_resource_writer_fence_path(self.f.owner)
        self.store.transact(lambda unit: unit.put(path, self.fence))
        self.store.transact(lambda unit: read.require_current(unit, 1007))
        with self.assertRaisesRegex(ContractError, "source_unavailable"):
            self.store.transact(lambda unit: read.require_current(unit, 1008))
        self.store.transact(lambda unit: unit.put(path, {**self.fence, "state": "frozen"}))
        with self.assertRaisesRegex(ContractError, "source_unavailable"):
            self.store.transact(lambda unit: read.require_current(unit, 1001))

    def test_slow_headers_can_use_remaining_budget_with_bounded_connection(self):
        seen = []

        async def slow_headers(request):
            bounds = request.extensions["timeout"]
            self.assertEqual((bounds["connect"], bounds["write"], bounds["pool"]), (4, 4, 4))
            # Mimic a provider that publishes headers after a cold start.
            await asyncio.wait_for(asyncio.sleep(4.1), bounds["read"])
            seen.append(request)
            return self.reply(request)

        self.client.transport = httpx.MockTransport(slow_headers)

        async def call_as_server_worker():
            return await anyio.to_thread.run_sync(self.client.read, UID, self.f.vault, self.fence)

        scope = asyncio.run(call_as_server_worker())
        self.assertEqual(scope.cursor.head(), self.authority["registry"])
        self.assertEqual(len(seen), 1)
        self.assertTrue(4.1 < seen[0].extensions["timeout"]["read"] <= 8)

    def test_caller_budget_includes_credential_setup(self):
        now = [100.0]
        self.client.clock = lambda: now[0]

        def token(*args, **kwargs):
            now[0] += 1.25
            return "google.workload.identity"

        self.client.token_factory = token
        self.client.read(UID, self.f.vault, self.fence, deadline=103)
        bounds = self.wire.call_args.args[0].extensions["timeout"]
        self.assertEqual(set(bounds.values()), {1.75})

    def test_total_deadline_cancels_trickling_response_and_sanitizes_failure_log(self):
        class TricklingBody(httpx.AsyncByteStream):
            received = 0
            closed = False

            async def __aiter__(self):
                for _ in range(30):
                    await asyncio.sleep(0.04)
                    self.received += 1
                    yield b" "

            async def aclose(self):
                self.closed = True

        body = TricklingBody()

        async def trickle(request):
            response = self.reply(request)
            return httpx.Response(200, headers=response.headers, stream=body)

        self.client.transport = httpx.MockTransport(trickle)
        with self.assertLogs("uvicorn.error.hub_user_authority", level="WARNING") as captured:
            with self.assertRaisesRegex(ContractError, "source_unavailable"):
                self.client.read(UID, self.f.vault, self.fence, deadline=time.monotonic() + 0.35)
        self.assertTrue(0 < body.received < 30)
        self.assertTrue(body.closed)
        self.assertRegex(
            captured.records[0].getMessage(),
            r"^hub_user_authority result=timeout stage=body "
            r"elapsed_ms=\d+ header_ms=\d+ body_ms=\d+$",
        )

    def test_frozen_gate_wrong_root_and_stale_evidence_fail_closed(self):
        with self.assertRaisesRegex(ContractError, "source_unavailable"):
            self.client.read(UID, self.f.vault, {**self.fence, "state": "frozen"})
        self.wire.assert_not_called()
        with self.assertRaisesRegex(ContractError, "source_unavailable"):
            self.client.read(UID, self.f.vault, {**self.fence, "transitionFingerprint": "b" * 64})
        with self.assertRaisesRegex(ContractError, "source_unavailable"):
            self.client.read(UID, self.f.vault, self.fence, minimum_epoch=3)
        self.authority["registryHistory"].pop()
        with self.assertRaisesRegex(ContractError, "source_unavailable"):
            self.client.read(UID, self.f.vault, self.fence)

    def test_catalogue_keeps_four_live_fence_checks_without_separate_begin_requests(self):
        client = firestore.Client(
            project="synthetic-hub", database="agent-hub", credentials=AnonymousCredentials()
        )
        self.addCleanup(client.close)
        rpc = MemoryRpc(client)
        client._firestore_api_internal = rpc
        store = FirestoreHubStore("synthetic-hub", "agent-hub", client=client)
        path = client.document(private_resource_writer_fence_path(self.f.owner))._document_path
        rpc.documents[path] = self.fence
        sources = Mock(clock=time.monotonic)
        sources.discover.return_value = {
            "portfolio": [],
            "user": {
                kind: item(None, state="uninitialized", evidence="not_prepared")
                for kind in ("watchlist", "channel_follows")
            },
        }
        catalogue = CatalogueService(
            VaultService(store, clock=lambda: 1000),
            sources,
            user_vaults=ScopedUserVaults(store, owner=self.f.owner, client=self.client),
        )
        self.assertEqual(catalogue.read(UID)["groups"][0]["status"], "uninitialized")
        self.assertEqual(self.wire.call_count, 2)
        self.assertEqual([kind for kind, _ in rpc.calls], ["get", "commit"] * 4)
        for kind, call in rpc.calls:
            request = call["request"]
            if kind == "get":
                self.assertEqual(list(request["documents"]), [path])
                self.assertEqual(request["new_transaction"]._pb.WhichOneof("mode"), "read_write")
            else:
                self.assertFalse(request["writes"])

    def test_overview_reuses_only_the_exact_verified_user_checkpoint_for_each_signed_packet(self):
        f = self.f
        VaultService(self.store, clock=lambda: 1000).bootstrap(UID, f.bootstrap(), BOOT)
        fence_path = private_resource_writer_fence_path(f.owner)
        self.store.transact(lambda unit: unit.put(fence_path, self.fence))
        source = ScopedUserVaults(self.store, owner=f.owner, client=self.client)
        service = tasks.TaskService(self.store, clock=lambda: 1000, user_vaults=source)
        f.registry = source.read(UID, f.vault).cursor.registry
        f.bundle = self.authority["registryHistory"][-1]
        ids = [f"synthetic_transferred_task_{n}" for n in range(4)]
        for ident in ids:
            operation = "create_" + ident
            service.create(
                UID, f.body(task=ident, operation=operation), operation, f.kid("device_sig")
            )
        expected = {ident: service.get(UID, ident) for ident in ids}
        body = {"contractVersion": CONTRACT_VERSION, "knownPacketVersions": [], "packetLimit": 4}
        overview = TaskOverviewService(self.store, clock=lambda: 1000, user_vaults=source)

        # Revoke the writer in a later authenticated checkpoint. Each carrier
        # must still be checked at the unique checkpoint that signed that task.
        following = f.make_bundle(previous=f.registry, revoked=("device_sig",), issued_at=975)
        revoked = f.verify(following, previous=f.registry)
        self.authority["registryHistory"].append(following)
        self.authority["registry"] = PrivateRegistryCursor(revoked, 2).head()
        with (
            patch("app.tasks.verify_registry", wraps=tasks.verify_registry) as replay,
            patch("app.tasks.verify_carrier", wraps=tasks.verify_carrier) as carriers,
        ):
            result = overview.overview(UID, f.vault, body)
        self.assertEqual(
            {item["taskId"]: item["packet"] for item in result["packets"]["items"]}, expected
        )
        self.assertEqual(replay.call_count, 0)
        self.assertEqual(carriers.call_count, 4)
        self.assertIsNone(source.read(UID, f.vault).verified_prefixes)
        selected = source.read(UID, f.vault, retain_prefixes=True)
        cache = selected.verified_prefixes
        self.assertEqual(cache.get(f.owner, selected.authority, 1, 950), f.registry)
        self.assertNotIn(
            f.kid("device_sig"), cache.get(f.owner, selected.authority, 2, 1000).active_key_ids
        )
        with self.assertRaises(ContractError):
            cache.get(f.owner, selected.authority, 1, 949)
        fork = copy.deepcopy(selected.authority)
        fork["registryHistory"][-1] = f.make_bundle(previous=f.registry, issued_at=976)
        self.assertIsNone(cache.get(f.owner, fork, 1, 1000))

        # A valid cached registry cannot turn an altered packet into a result.
        path = tasks._paths(f.owner, f.vault, ids[0], 1)

        def tamper(unit):
            packet = unit.get(path)
            packet["keyProofs"] = tasks._proofs(following)
            unit.put(path, packet)

        self.store.transact(tamper)
        with self.assertRaises(StoreUnavailable):
            overview.overview(UID, f.vault, body)

        # A changed local writer during the remote read invalidates this request.
        reply = self.wire.side_effect

        def change_fence(request):
            response = reply(request)
            self.store.transact(
                lambda unit: unit.put(fence_path, {**self.fence, "state": "frozen"})
            )
            return response

        self.wire.side_effect = change_fence
        with self.assertRaisesRegex(ContractError, "source_unavailable"):
            overview.overview(UID, f.vault, body)

    def test_owner_overview_uses_current_user_scope_when_the_original_vault_has_transferred(self):
        VaultService(self.store, clock=lambda: 1000).bootstrap(UID, self.f.bootstrap(), BOOT)
        path = private_resource_writer_fence_path(self.f.owner)
        self.store.transact(lambda unit: unit.put(path, self.fence))
        body = {"contractVersion": CONTRACT_VERSION, "knownPacketVersions": [], "packetLimit": 4}
        consumer = TaskOverviewService(
            self.store,
            clock=lambda: 1000,
            user_vaults=ScopedUserVaults(self.store, owner=self.f.owner, client=self.client),
        )
        self.assertEqual(consumer.overview(UID, self.f.vault, body)["tasks"]["items"], [])
        self.wire.assert_called_once()
        with self.assertRaisesRegex(ContractError, "source_unavailable"):
            TaskOverviewService(self.store, clock=lambda: 1000).overview(UID, self.f.vault, body)
