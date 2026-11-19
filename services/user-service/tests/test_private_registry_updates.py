"""Exercise the transferred registry head and immutable checkpoint write together."""

import unittest

import test_registry_transition as fixture

from app.private_resources.authority_cutover import UserAuthorityCutover
from app.private_resources.authority_views import PrivateAuthorityViews
from app.private_resources.registry_updates import (
    REGISTRY_UPDATE_PROFILE,
    RegistryUpdate,
    RegistryUpdates,
)
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import verify_jws
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.private_resources import PRIVATE_AUTHORITY_PROFILE


class RegistryUpdateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.RegistryTransitionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.cutover = UserAuthorityCutover(self.fixture.store)
        self.fixture.stage_frozen_scope()
        installed = self.cutover.install(fixture.UID, fixture.VAULT, self.fixture.packet, now=1000)
        first = self.fixture.packet["firstBundle"]
        checkpoint = verify_jws(
            first["checkpoint"], self.fixture.vault["rootJwk"], typ="fv-control+jws"
        )
        self.bundle = {
            **first,
            "checkpoint": self.fixture.sign(
                {
                    **checkpoint,
                    "registrySequence": checkpoint["registrySequence"] + 1,
                    "previousDigest": installed["registryStart"]["checkpointDigest"],
                    "issuedAt": 1001,
                }
            ),
        }
        self.request = RegistryUpdate(
            contractVersion=CONTRACT_VERSION,
            profile=REGISTRY_UPDATE_PROFILE,
            ownerSubject=fixture.OWNER,
            vaultId=fixture.VAULT,
            operationId="synthetic_registry_update_0001",
            expectedVaultVersion=installed["nextVaultVersion"],
            registryBundle=self.bundle,
        )
        self.writer = RegistryUpdates(self.fixture.store, clock=lambda: 1001)

    def test_same_root_advances_once_and_the_live_view_contains_the_new_checkpoint(self):
        receipt = self.writer.update(fixture.UID, self.request)
        self.assertEqual(receipt["vaultVersion"], self.request.expectedVaultVersion + 1)
        self.assertEqual(self.writer.update(fixture.UID, self.request), receipt)
        lookup = PrivateAuthorityViews(self.fixture.store).lookup(
            fixture.UID,
            {
                "contractVersion": CONTRACT_VERSION,
                "profile": PRIVATE_AUTHORITY_PROFILE,
                "consumer": "hub",
                "ownerSubject": fixture.OWNER,
                "vaultId": fixture.VAULT,
                "sourceId": None,
                "minimumRegistryEpoch": 2,
                "nonce": "synthetic_registry_update_lookup",
            },
            now=1001,
        )["authority"]
        self.assertEqual(lookup["registry"], receipt["registry"])
        self.assertEqual(lookup["registryHistory"][-1], self.bundle)
        self.assertEqual(lookup["registry"]["registryEpoch"], 2)
        with self.assertRaisesRegex(ContractError, "idempotency_conflict"):
            self.writer.update(
                fixture.UID, self.request.model_copy(update={"expectedVaultVersion": 3})
            )
        with self.assertRaisesRegex(ContractError, "version_conflict"):
            self.writer.update(
                fixture.UID,
                self.request.model_copy(update={"operationId": "synthetic_registry_update_0002"}),
            )

    def test_old_bundle_and_foreign_scope_do_not_change_the_current_head(self):
        before = self.fixture.heads.read(fixture.OWNER)
        with self.assertRaisesRegex(ContractError, "insufficient_scope"):
            self.writer.update("unrelated-synthetic-owner", self.request)
        before_handover = self.fixture.vault["registryHistory"][-1]
        with self.assertRaises(ContractError):
            self.writer.update(
                fixture.UID, self.request.model_copy(update={"registryBundle": before_handover})
            )
        self.assertEqual(self.fixture.heads.read(fixture.OWNER), before)
