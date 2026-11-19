"""Signed, encrypted alias CAS under the selected User authority."""

import unittest
from unittest.mock import Mock, patch

import test_registry_transition as fixture
from fastapi.testclient import TestClient
from test_private_recovery import OWNER, UID, VAULT

from app.main import app
from app.private_resources.api import owner_display_names
from app.private_resources.authority_cutover import UserAuthorityCutover
from app.private_resources.display_names import PrivateDisplayNames
from app.private_resources.source_invalidations import SourceInvalidations
from app.private_resources.source_registrations import HoldingsRegistrations, current_registry
from folioview_shared.auth import CurrentUser, require_google_user
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import sign_jws
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.private_display_names import (
    DISPLAY_NAME_PROFILE,
    encrypt_display_name,
)


class UserDisplayNameTests(unittest.TestCase):
    def setUp(self):
        sample = fixture.RegistryTransitionTests()
        sample.setUp()
        self.addCleanup(sample.doCleanups)
        self.cutover = UserAuthorityCutover(sample.store)
        sample.stage_frozen_scope()
        self.cutover.install(UID, VAULT, sample.packet, now=1000)
        self.store = sample.store
        self.signer = sample.signing_keys["device_sig"]
        self.owner_fields = {
            "contractVersion": CONTRACT_VERSION,
            "ownerSubject": OWNER,
            "vaultId": VAULT,
        }
        self.names = PrivateDisplayNames(self.store, clock=lambda: 1000)
        self.source = "synthetic_named_holdings"
        operation = "synthetic_named_holdings_registration"
        head = sample.transition["nextHead"]
        self.registry_fields = {
            key: head[key] for key in ("registrySequence", "checkpointDigest", "keyEpoch")
        }
        registration = sign_jws(
            {
                **self.owner_fields,
                **self.registry_fields,
                "artifactType": "control_command",
                "stableOperationId": operation,
                "action": "manual_source_create",
                "targetId": self.source,
                "expectedVersion": 0,
                "expectedSourceEpoch": None,
                "parameters": {},
            },
            self.signer,
            typ="fv-control+jws",
        )
        registered = HoldingsRegistrations(self.store, clock=lambda: 1000).register(
            UID, VAULT, self.source, registration, operation
        )
        self.ref = registered["source"]["resourceRef"]
        _, registry, _ = current_registry(self.cutover, UID, VAULT, 1000)
        self.device, self.recovery = [
            next(
                registry.cert(key, now=1000)
                for key in registry.active_key_ids
                if registry.cert(key, now=1000)["role"] == role
            )
            for role in ("device_sig", "recovery_enc")
        ]

    def sample(self, operation, revision=1, prior=None):
        context = {
            **self.owner_fields,
            "profile": DISPLAY_NAME_PROFILE,
            "rootKeyId": self.device["issuerKeyId"],
            "ref": self.ref,
            "purpose": "owner_display_name",
            "revision": revision,
            "stableOperationId": operation,
            "recipientKeyId": self.recovery["keyId"],
        }
        return sign_jws(
            {
                **context,
                **self.registry_fields,
                "artifactType": "private_display_name_update",
                "deviceSigningKeyId": self.device["keyId"],
                "issuedAt": 1000,
                "expectedRevision": revision - 1,
                "previousFingerprint": prior,
                "envelope": encrypt_display_name(
                    "Synthetic alias", self.recovery["publicJwk"], context=context
                ),
            },
            self.signer,
            typ="fv-control+jws",
        )

    def test_ciphertext_and_exact_replay_survive_source_retirement(self):
        operation = "synthetic_display_name_001"
        command = self.sample(operation)
        original = self.names.write(UID, VAULT, self.source, operation, command)
        self.assertEqual(self.names.read(UID, VAULT, None, None)["items"], [original["item"]])
        fingerprint = original["item"]["state"]["operationFingerprint"]
        second = "synthetic_display_name_002"
        second_command = self.sample(second, 2, fingerprint)
        latest = self.names.write(UID, VAULT, self.source, second, second_command)
        self.assertEqual(latest["item"]["state"]["revision"], 2)
        with self.assertRaisesRegex(ContractError, "idempotency_conflict"):
            self.names.write(UID, VAULT, self.source, operation, self.sample(operation))
        SourceInvalidations(self.store, clock=lambda: 1000).invalidate(
            {
                "contractVersion": CONTRACT_VERSION,
                "ownerSubject": OWNER,
                "mutationId": "synthetic_named_holdings_retire_001",
                "ref": self.ref,
                "expectedSourceEpoch": 1,
                "newSourceEpoch": 2,
                "reason": "deleted",
            }
        )
        self.assertEqual(self.names.read(UID, VAULT, None, None)["items"], [])
        self.assertEqual(self.names.read(UID, VAULT, self.source, operation), original)
        self.assertEqual(self.names.write(UID, VAULT, self.source, operation, command), original)
        with self.assertRaisesRegex(ContractError, "not_found"):
            new = "synthetic_display_name_003"
            self.names.write(
                UID,
                VAULT,
                self.source,
                new,
                self.sample(new, 3, latest["item"]["state"]["operationFingerprint"]),
            )

    def test_owner_routes_require_the_exact_owner_and_proxy(self):
        url = f"/api/v3/private-resources/vaults/{VAULT}/display-names/read"
        packet = {
            **self.owner_fields,
            "profile": DISPLAY_NAME_PROFILE,
            "sourceId": None,
            "operationId": None,
        }
        headers = {
            "X-FolioView-Contract": CONTRACT_VERSION,
            "X-FolioView-Proxy-Authorization": "Bearer synthetic_workload",
        }
        with (
            TestClient(app) as client,
            patch.dict(
                app.dependency_overrides,
                {
                    require_google_user: lambda: CurrentUser(
                        uid=UID, email=None, displayName=None, photoURL=None
                    ),
                    owner_display_names: lambda: self.names,
                },
            ),
            patch("app.private_resources.api.configured_owner_proxy", return_value=Mock()),
        ):
            self.assertEqual(client.post(url, json=packet, headers=headers).status_code, 200)
            self.assertEqual(
                client.post(
                    url, json={**packet, "ownerSubject": "0" * 64}, headers=headers
                ).status_code,
                404,
            )
            self.assertEqual(
                client.post(
                    url, json=packet, headers={"X-FolioView-Contract": CONTRACT_VERSION}
                ).status_code,
                401,
            )
