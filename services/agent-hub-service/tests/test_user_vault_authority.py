"""A Hub lookup keeps the signed User epoch bound to its exact transferred writer."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import httpx
from fixtures import BOOT, UID, VaultFixture

from app.store import SQLiteHubStore, private_resource_writer_fence_path
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
        self.f = f = VaultFixture()
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
