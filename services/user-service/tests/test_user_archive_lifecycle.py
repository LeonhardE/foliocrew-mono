"""Return exact retained archive commands and receipts from the transferred User vault."""

import hashlib
import unittest

import test_registry_transition as fixture
from test_private_recovery import OWNER, UID, VAULT

from app.private_resources.archive_lifecycle import PrivateArchiveLifecycle
from app.private_resources.authority_cutover import UserAuthorityCutover
from app.private_resources.legacy_baselines import LegacyVaultBaselines, verified_baseline
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import strict_json_loads
from folioview_shared.encrypted.legacy_archive import (
    PROFILE,
    advance_legacy_archive,
    legacy_archive_receipt,
    verify_legacy_archive_history,
)


class UserArchiveLifecycleTests(unittest.TestCase):
    def test_original_signed_lifecycle_and_receipt_are_read_after_transfer(self):
        sample = fixture.RegistryTransitionTests()
        sample.setUp()
        self.addCleanup(sample.doCleanups)
        cutover = UserAuthorityCutover(sample.store)
        reader = PrivateArchiveLifecycle(sample.store, clock=lambda: 1000)
        nonce = "synthetic_archive_read_once"
        with self.assertRaisesRegex(ContractError, "not_found"):
            reader.read(UID, VAULT, nonce, None)

        baseline = cutover.verifier.baselines.read(OWNER, VAULT, sample.digest)
        registry, _, _ = cutover.verifier.original_history(strict_json_loads(baseline), 1000)
        state = verify_legacy_archive_history(sample.vault, registry.registry, None)
        head = sample.transition["previousHead"]
        history = {**sample.scope, "initialArchiveDigest": state["digest"], "history": []}
        for position, (action, extra) in enumerate(
            (
                ("recovery_authorize", {"newArchiveDigest": "d" * 64}),
                ("recovery_revoke", {}),
            )
        ):
            payload = {
                **sample.scope,
                **{key: head[key] for key in ("registrySequence", "checkpointDigest", "keyEpoch")},
                "contractVersion": CONTRACT_VERSION,
                "profile": PROFILE,
                "action": action,
                "stableOperationId": f"synthetic_original_archive_operation_{position}",
                "expectedVaultVersion": 1,
                "expectedLifecycleVersion": state["version"],
                "expectedArchiveRevision": state["revision"],
                "expectedArchiveDigest": state["digest"],
                "issuedAt": 900 + position,
                "expiresAt": 960 + position,
                "authorizationId": "original_recovery_authorization",
                **extra,
            }
            signed = sample.sign(payload)
            state = advance_legacy_archive(state, payload, signed, payload["issuedAt"])
            history["history"].append(
                {
                    "command": signed,
                    "receipt": legacy_archive_receipt(
                        sample.vault, payload, state, signed, payload["issuedAt"]
                    ),
                }
            )

        prepared = verified_baseline(OWNER, sample.vault, history, now=1000)
        recorded = hashlib.sha256(prepared).hexdigest()
        LegacyVaultBaselines(sample.store).stage(
            OWNER, sample.vault, history, expected_digest=recorded, now=1000
        )
        # The signed archive boundary contains its original lifecycle version.
        sample.transition["archive"]["version"] = 3
        sample.packet["signedTransition"] = sample.sign(sample.transition)
        sample.stage_frozen_scope(baselineDigest=recorded)
        cutover.install(UID, VAULT, sample.packet, now=1000)
        result = reader.read(UID, VAULT, nonce, None)
        self.assertEqual(result["nonce"], nonce)
        self.assertEqual(result["state"]["history"], history["history"])
        self.assertEqual(result["state"]["archive"], sample.vault["archive"])
        self.assertEqual(
            result["state"]["registrySequence"], sample.transition["nextHead"]["registrySequence"]
        )
        self.assertEqual(
            result["originalCheckpoints"], [sample.vault["registryHistory"][0]["checkpoint"]]
        )
        operation = history["history"][1]["receipt"]["operationId"]
        self.assertEqual(
            reader.read(UID, VAULT, nonce, operation)["receipt"], history["history"][1]["receipt"]
        )
        with self.assertRaisesRegex(ContractError, "not_found"):
            reader.read("other-account", VAULT, nonce, operation)
