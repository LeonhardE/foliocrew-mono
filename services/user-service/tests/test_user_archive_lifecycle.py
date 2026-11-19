"""Return exact retained archive commands and receipts from the transferred User vault."""

import hashlib
import unittest
from unittest.mock import patch

import test_registry_transition as fixture
from test_private_recovery import OWNER, UID, VAULT

from app.private_resources.archive_lifecycle import PrivateArchiveLifecycle
from app.private_resources.authority_cutover import UserAuthorityCutover
from app.private_resources.authority_views import PrivateAuthorityViews
from app.private_resources.legacy_baselines import LegacyVaultBaselines, verified_baseline
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import b64url_encode, canonical_json, strict_json_loads
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

    def start_transferred_archive(self):
        sample = fixture.RegistryTransitionTests()
        sample.setUp()
        self.addCleanup(sample.doCleanups)
        cutover = UserAuthorityCutover(sample.store)
        sample.stage_frozen_scope()
        cutover.install(UID, VAULT, sample.packet, now=1000)
        return sample, PrivateArchiveLifecycle(sample.store, clock=lambda: 1000)

    @staticmethod
    def command(sample, state, action, operation, **action_fields):
        return sample.sign(
            {
                **sample.scope,
                **{key: state[key] for key in ("registrySequence", "checkpointDigest", "keyEpoch")},
                "contractVersion": CONTRACT_VERSION,
                "profile": PROFILE,
                "action": action,
                "stableOperationId": operation,
                "expectedVaultVersion": state["vaultVersion"],
                "expectedLifecycleVersion": state["lifecycleVersion"],
                "expectedArchiveRevision": state["archiveRevision"],
                "expectedArchiveDigest": state["archiveDigest"],
                "issuedAt": 1000,
                "expiresAt": 1060,
                **action_fields,
            }
        )

    def test_replacement_and_recovery_controls_advance_exactly_once(self):
        sample, writer = self.start_transferred_archive()
        nonce = "synthetic_archive_lifecycle_nonce"
        initial = writer.read(UID, VAULT, nonce, None)["state"]
        authority = PrivateAuthorityViews(sample.store)
        original = authority.owner_current(UID, nonce, now=1000)
        self.assertNotIn("archiveLifecycle", original["proof"])
        replacement = {
            **initial["archive"],
            "iv": b64url_encode(bytes(range(12))),
            "ciphertext": b64url_encode(bytes(range(16, 32))),
        }
        operation = "synthetic_transferred_replacement"
        command = self.command(
            sample,
            initial,
            "archive_replace",
            operation,
            mode="rewrap",
            authorizationId=None,
            newArchiveDigest=hashlib.sha256(canonical_json(replacement)).hexdigest(),
        )
        with self.assertRaisesRegex(ContractError, "recipient_binding_mismatch"):
            writer.advance(UID, VAULT, operation, command, initial["archive"])
        receipt = writer.advance(UID, VAULT, operation, command, replacement)
        changed = writer.read(UID, VAULT, nonce, None)["state"]
        self.assertEqual(changed["archive"], replacement)
        self.assertEqual(changed["archiveRevision"], initial["archiveRevision"] + 1)
        self.assertEqual(changed["history"], [{"command": command, "receipt": receipt}])
        current = authority.owner_current(UID, nonce, now=1000)
        self.assertEqual(current["vault"]["archive"], replacement)
        self.assertEqual(current["proof"]["archiveLifecycle"]["state"], changed)
        self.assertEqual(
            current["proof"]["signedTransition"], original["proof"]["signedTransition"]
        )
        self.assertEqual(writer.read(UID, VAULT, nonce, operation)["receipt"], receipt)

        authorize = "synthetic_transferred_authorize"
        scope = {"authorizationId": "synthetic_transferred_grant"}
        approval = self.command(
            sample, changed, "recovery_authorize", authorize, newArchiveDigest="d" * 64, **scope
        )
        writer.advance(UID, VAULT, authorize, approval, None)
        granted = writer.read(UID, VAULT, nonce, None)["state"]
        self.assertEqual(granted["pendingAuthorization"]["status"], "active")
        revoke = "synthetic_transferred_revoke"
        revocation = self.command(sample, granted, "recovery_revoke", revoke, **scope)
        writer.advance(UID, VAULT, revoke, revocation, None)
        self.assertEqual(writer.advance(UID, VAULT, operation, command, replacement), receipt)
        final = writer.read(UID, VAULT, nonce, None)["state"]
        self.assertIsNone(final["pendingAuthorization"])
        self.assertEqual(final["archive"], replacement)
        self.assertEqual(final["lifecycleVersion"], initial["lifecycleVersion"] + 3)

        differently_signed = self.command(
            sample,
            initial,
            "archive_replace",
            operation,
            mode="passkey_change",
            authorizationId=None,
            newArchiveDigest=hashlib.sha256(canonical_json(replacement)).hexdigest(),
        )
        with self.assertRaisesRegex(ContractError, "idempotency_conflict"):
            writer.advance(UID, VAULT, operation, differently_signed, replacement)

    def test_pre_transfer_stale_and_failed_atomic_commits_never_publish_a_receipt(self):
        sample, writer = self.start_transferred_archive()
        nonce = "synthetic_archive_commit_nonce"
        snapshot = writer.read(UID, VAULT, nonce, None)["state"]
        first = "synthetic_archive_approval_one"
        second = "synthetic_archive_approval_two"
        approval = self.command(
            sample,
            snapshot,
            "recovery_authorize",
            first,
            authorizationId="first_approval",
            newArchiveDigest="d" * 64,
        )
        stale = self.command(
            sample,
            snapshot,
            "recovery_authorize",
            second,
            authorizationId="second_approval",
            newArchiveDigest="e" * 64,
        )
        with self.assertRaisesRegex(ContractError, "not_found"):
            writer.advance("different-owner", VAULT, first, approval, None)
        with patch.object(
            writer.cutover, "_transaction", side_effect=ContractError("version_conflict")
        ):
            with self.assertRaisesRegex(ContractError, "version_conflict"):
                writer.advance(UID, VAULT, first, approval, None)
        self.assertEqual(writer.read(UID, VAULT, nonce, None)["state"], snapshot)
        with self.assertRaisesRegex(ContractError, "not_found"):
            writer.read(UID, VAULT, nonce, first)
        writer.advance(UID, VAULT, first, approval, None)
        with self.assertRaisesRegex(ContractError, "version_conflict"):
            writer.advance(UID, VAULT, second, stale, None)
        with self.assertRaisesRegex(ContractError, "not_found"):
            writer.read(UID, VAULT, nonce, second)
