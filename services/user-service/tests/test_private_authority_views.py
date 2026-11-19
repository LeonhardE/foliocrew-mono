"""Read only the transferred User scope and the requested Portfolio incarnation."""

import unittest
from unittest.mock import Mock, patch

import test_registry_transition as fixture
from fastapi.testclient import TestClient

from app.main import app
from app.private_resources.api import (
    HUB_AUTHORITY_PATH,
    PORTFOLIO_AUTHORITY_PATH,
    live_authority_views,
)
from app.private_resources.authority_cutover import UserAuthorityCutover
from app.private_resources.authority_views import OWNER_CURRENT_PROFILE, PrivateAuthorityViews
from app.private_resources.directory import PrivateResourceDirectory
from app.private_resources.recovery import COLLECTION as HEADS
from app.private_resources.report_sources import HOLDINGS_FENCES, holdings_fence_key
from app.private_resources.source_invalidations import SOURCE_INDEX, SourceInvalidations
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json
from folioview_shared.encrypted.private_resources import (
    PRIVATE_AUTHORITY_PROFILE,
    source_index_digest,
)


class AuthorityViewTests(unittest.TestCase):
    def setUp(self):
        self.sample = fixture.RegistryTransitionTests()
        self.sample.setUp()
        self.addCleanup(self.sample.doCleanups)
        self.store = self.sample.store
        self.cutover = UserAuthorityCutover(self.store)
        self.sample.stage_frozen_scope()
        self.cutover.install(fixture.UID, fixture.VAULT, self.sample.packet, now=1000)
        self.viewer = PrivateAuthorityViews(self.store)
        self.request = {
            "contractVersion": CONTRACT_VERSION,
            "profile": PRIVATE_AUTHORITY_PROFILE,
            "consumer": "hub",
            "ownerSubject": fixture.OWNER,
            "vaultId": fixture.VAULT,
            "sourceId": None,
            "minimumRegistryEpoch": 2,
            "nonce": "synthetic_live_authority_read_01",
        }

    def test_hub_receives_transferred_root_and_only_current_source_index(self):
        with self.assertRaisesRegex(ContractError, "insufficient_scope"):
            self.viewer.lookup("another-owner", self.request, now=1000)
        with self.assertRaisesRegex(ContractError, "rollback_detected"):
            self.viewer.lookup(fixture.UID, {**self.request, "minimumRegistryEpoch": 3}, now=1000)

        output = self.viewer.lookup(fixture.UID, self.request, now=1000)
        self.assertEqual(output["nonce"], self.request["nonce"])
        authority = output["authority"]
        self.assertEqual(authority["registry"]["registryEpoch"], 2)
        self.assertEqual(authority["registryHistory"], [self.sample.packet["firstBundle"]])
        self.assertEqual(authority["sources"], [])
        self.assertNotIn("ciphertext", authority)
        self.assertNotIn("devices", authority)

    def test_owner_cold_read_returns_authenticated_current_epoch_and_the_original_archive(self):
        nonce = self.request["nonce"]
        result = self.viewer.owner_current(fixture.UID, nonce, now=1000)
        self.assertEqual(result["profile"], OWNER_CURRENT_PROFILE)
        self.assertEqual((result["ownerSubject"], result["nonce"]), (fixture.OWNER, nonce))
        self.assertEqual(result["vault"]["archive"], self.sample.vault["archive"])
        self.assertEqual(result["vault"]["rootKeyId"], self.sample.vault["rootKeyId"])
        self.assertEqual(result["vault"]["registryHistory"], [self.sample.packet["firstBundle"]])
        self.assertEqual(
            result["proof"]["signedTransition"], self.sample.packet["signedTransition"]
        )
        self.assertEqual(result["proof"]["registry"]["registryEpoch"], 2)
        self.assertEqual(result["proof"]["sources"], [])
        with self.assertRaisesRegex(ContractError, "not_found"):
            self.viewer.owner_current("unrelated-synthetic-owner", nonce, now=1000)

    def test_portfolio_selected_incarnation_is_unavailable_after_invalidation(self):
        source = "synthetic_holdings"
        ref = {
            "kind": "holdings",
            "sourceService": "portfolio",
            "resourceId": source,
            "incarnation": "synthetic_incarnation",
        }
        binding = {"ref": ref, "sourceEpoch": 1}
        entries = [{"binding": binding, "state": "active"}]
        scope = {"ownerSubject": fixture.OWNER, "vaultId": fixture.VAULT}
        request = {**self.request, "consumer": "portfolio", "sourceId": source}
        head = self.sample.heads.read(fixture.OWNER)
        key = holdings_fence_key(fixture.OWNER, fixture.VAULT, source)
        with self.store.connection() as db:
            for table, ident, value in (
                (HEADS, fixture.OWNER, {**head, "sourcesDigest": source_index_digest(entries)}),
                (SOURCE_INDEX, fixture.OWNER, {**scope, "entries": entries}),
                (
                    HOLDINGS_FENCES,
                    key,
                    {**scope, "binding": binding, "state": "eligible", "currentRevision": 0},
                ),
            ):
                db.execute(
                    f"INSERT OR REPLACE INTO {table} VALUES (?, ?)",
                    (ident, canonical_json(value).decode()),
                )
        with patch(
            "app.private_resources.authority_views._recipient_keys",
            return_value=(["writer_A"], ["recipient_A", "recovery_A"]),
        ):
            output = self.viewer.lookup(fixture.UID, request, now=1000)
            self.assertEqual(output["authority"]["resourceRef"], ref)
            self.assertEqual(output["authority"]["sourceEpoch"], 1)
            self.assertNotIn("sources", output["authority"])
        directory = PrivateResourceDirectory(self.store)
        before = directory.read(fixture.UID, fixture.VAULT, request["nonce"])
        self.assertEqual(before["holdings"], [{**binding, "state": "active", "revision": 0}])
        self.assertEqual(before["registry"]["registryEpoch"], 2)
        self.assertEqual(
            {item["kind"] for item in before["lists"]}, {"watchlist", "channel_follows"}
        )
        self.assertTrue(all(item["state"] == "uninitialized" for item in before["lists"]))
        with self.assertRaisesRegex(ContractError, "not_found"):
            directory.read("unrelated-synthetic-owner", fixture.VAULT, request["nonce"])
        SourceInvalidations(self.store, clock=lambda: 1000).invalidate(
            {
                "contractVersion": CONTRACT_VERSION,
                "ownerSubject": fixture.OWNER,
                "mutationId": "synthetic_source_delete_000001",
                "ref": ref,
                "expectedSourceEpoch": 1,
                "newSourceEpoch": 2,
                "reason": "deleted",
            }
        )
        with self.assertRaisesRegex(ContractError, "source_unavailable"):
            self.viewer.lookup(fixture.UID, request, now=1000)
        after = directory.read(fixture.UID, fixture.VAULT, request["nonce"])
        self.assertEqual(after["holdings"], [])
        self.assertEqual(after["sourcesDigest"], source_index_digest([]))

    def test_production_authority_read_confines_authenticated_owner(self):
        verifier = Mock()
        verifier.verify_private_authority_read.return_value = fixture.UID
        headers = {
            "Authorization": "Bearer synthetic_workload",
            "X-FolioView-Delegation": "synthetic_delegation",
            "X-FolioView-Contract": CONTRACT_VERSION,
        }
        expected_owner = self.request["ownerSubject"]
        with (
            TestClient(app) as client,
            patch("app.private_resources.api.time.time", return_value=1000),
            patch("app.private_resources.api.configured_verifier", return_value=verifier),
            patch.object(self.viewer.cutover, "_named_store"),
            patch.dict(app.dependency_overrides, {live_authority_views: lambda: self.viewer}),
        ):
            for configured, status in (
                (None, 503),
                ("*", 503),
                ("0" * 64, 404),
                (expected_owner, 200),
            ):
                environment = {"K_SERVICE": "synthetic-user"}
                if configured is not None:
                    environment["USER_PRIVATE_SELECTED_OWNER"] = configured
                with self.subTest(status=status), patch.dict("os.environ", environment, clear=True):
                    response = client.post(HUB_AUTHORITY_PATH, headers=headers, json=self.request)
                    self.assertEqual(response.status_code, status, response.text)
                    self.assertEqual(response.headers["cache-control"], "no-store")

    def test_each_route_limits_delegation_to_its_fixed_consumer_and_audience(self):
        verifier = Mock()
        verifier.verify_private_authority_read.return_value = fixture.UID
        headers = {
            "Authorization": "Bearer synthetic_workload",
            "X-FolioView-Delegation": "synthetic_delegation",
            "X-FolioView-Contract": CONTRACT_VERSION,
        }
        with (
            TestClient(app) as client,
            patch("app.private_resources.api.time.time", return_value=1000),
            patch("app.private_resources.api.configured_verifier", return_value=verifier) as config,
        ):
            with patch.dict("os.environ", {"USER_PRIVATE_AUTHORITY_READS": "false"}):
                response = client.post(HUB_AUTHORITY_PATH, headers=headers, json=self.request)
                self.assertEqual(response.status_code, 404)
            with patch.dict(app.dependency_overrides, {live_authority_views: lambda: self.viewer}):
                response = client.post(HUB_AUTHORITY_PATH, headers=headers, json=self.request)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertEqual(
                    verifier.verify_private_authority_read.call_args.kwargs["consumer"], "hub"
                )
                self.assertEqual(config.call_args.args[1], HUB_AUTHORITY_PATH)
                response = client.post(
                    PORTFOLIO_AUTHORITY_PATH,
                    headers=headers,
                    json={**self.request, "consumer": "portfolio", "sourceId": "missing_holdings"},
                )
                self.assertEqual(response.status_code, 404, response.text)
                self.assertEqual(
                    verifier.verify_private_authority_read.call_args.kwargs["consumer"], "portfolio"
                )
                self.assertEqual(config.call_args.args[1], PORTFOLIO_AUTHORITY_PATH)
