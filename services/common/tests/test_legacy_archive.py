"""Verify original archive receipts using a real synthetic Root and verified history."""

import hashlib
import unittest
from copy import deepcopy

from test_encrypted_authority import AuthorityFixture

from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import signing_input_fingerprint
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import b64url_encode, canonical_json
from folioview_shared.encrypted.legacy_archive import (
    PROFILE,
    advance_legacy_archive,
    archive_deletion_outcome,
    legacy_archive_receipt,
    verify_legacy_archive_command,
    verify_legacy_archive_history,
    verify_retired_archive_history,
    verify_transferred_archive_history,
)
from folioview_shared.encrypted.private_resources import PrivateRegistryCursor


def digest(value):
    return hashlib.sha256(canonical_json(value)).hexdigest()


class LegacyArchiveTests(unittest.TestCase):
    def setUp(self):
        self.f = AuthorityFixture()
        self.scope = {
            "vaultId": self.f.vault,
            "rootKeyId": self.f.root_id,
            "ownerSubject": self.f.owner,
        }
        archive = {
            **self.scope,
            "profile": "folioview.passkey-vault.v1",
            "credentialId": b64url_encode(b"synthetic_credential"),
            "prfSalt": b64url_encode(b"x" * 32),
            "iv": b64url_encode(b"y" * 12),
            "ciphertext": b64url_encode(b"z" * 40),
        }
        next_bundle = self.f.make_bundle(previous=self.f.registry)
        self.registry = self.f.verify(next_bundle, previous=self.f.registry)
        self.vault = {
            **self.scope,
            "rootJwk": self.f.root_public,
            "archive": archive,
            "version": 2,
            "registryHistory": [self.f.bundle, next_bundle],
        }
        self.state = verify_legacy_archive_history(self.vault, self.registry, None)
        self.row = {**self.scope, "initialArchiveDigest": digest(archive), "history": []}

    def apply(self, action, at, **detail):
        body = {
            **self.scope,
            "contractVersion": CONTRACT_VERSION,
            "profile": PROFILE,
            "action": action,
            "stableOperationId": f"synthetic_archive_operation_{at}",
            "expectedVaultVersion": 1,
            "expectedLifecycleVersion": self.state["version"],
            "expectedArchiveRevision": self.state["revision"],
            "expectedArchiveDigest": self.state["digest"],
            "registrySequence": 1,
            "checkpointDigest": self.f.registry.checkpoint_digest,
            "keyEpoch": self.f.registry.key_epoch,
            "issuedAt": at,
            "expiresAt": at + 60,
            **detail,
        }
        command = self.f.sign(body, "root")
        payload = verify_legacy_archive_command(command, self.vault)
        state = advance_legacy_archive(self.state, payload, command, at)
        receipt = legacy_archive_receipt(self.vault, payload, state, command, at)
        item = {"command": command, "receipt": receipt}
        state["operations"] = {**self.state["operations"], body["stableOperationId"]: item}
        self.state = state
        self.row["history"].append(item)
        return item

    def test_exact_removal_outcome_survives_withdrawal_without_reusing_a_changed_command(self):
        operation = "synthetic_archive_original_delete"
        payload = {
            **self.scope,
            "contractVersion": CONTRACT_VERSION,
            "profile": PROFILE,
            "action": "archive_delete",
            "stableOperationId": operation,
            "expectedVaultVersion": self.vault["version"],
            "expectedLifecycleVersion": 0,
            "expectedArchiveRevision": 0,
            "expectedArchiveDigest": self.state["digest"],
            "registrySequence": self.registry.registry_sequence,
            "checkpointDigest": self.registry.checkpoint_digest,
            "keyEpoch": self.registry.key_epoch,
            "issuedAt": 1000,
            "expiresAt": 1060,
        }
        command = self.f.sign(payload, "root")
        check = archive_deletion_outcome(self.vault, self.registry, self.state, command)
        self.assertEqual(check["outcome"], "unresolved")
        item = self.apply(
            "archive_delete_withdraw",
            1001,
            deletionOperationId=operation,
            deletionCommandFingerprint=signing_input_fingerprint(command),
            deletionLifecycleVersion=0,
            expectedVaultVersion=self.vault["version"],
            registrySequence=self.registry.registry_sequence,
        )
        check = archive_deletion_outcome(self.vault, self.registry, self.state, command)
        self.assertEqual(check["outcome"], "withdrawn")
        self.assertEqual(check["receipt"], item["receipt"])
        altered = self.f.sign({**payload, "expiresAt": 1061}, "root")
        with self.assertRaisesRegex(ContractError, "idempotency_conflict"):
            archive_deletion_outcome(self.vault, self.registry, self.state, altered)

    def test_history_binds_original_authorization_revocation_and_ciphertext(self):
        replacement = {
            **self.vault["archive"],
            "ciphertext": b64url_encode(b"replacement_ciphertext"),
        }
        self.apply(
            "recovery_authorize",
            1000,
            authorizationId="restore_candidate",
            newArchiveDigest=digest(replacement),
        )
        self.apply("recovery_revoke", 1001, authorizationId="restore_candidate")
        self.apply(
            "archive_replace",
            1002,
            mode="passkey_change",
            authorizationId=None,
            newArchiveDigest=digest(replacement),
        )
        vault = {**self.vault, "archive": replacement}
        result = verify_legacy_archive_history(vault, self.registry, self.row)
        self.assertEqual(result, self.state)
        for tamper in ("archive", "receipt", "checkpoint", "owner"):
            candidate, history = deepcopy(vault), deepcopy(self.row)
            if tamper == "archive":
                candidate["archive"] = self.vault["archive"]
            elif tamper == "receipt":
                history["history"][0]["receipt"]["archiveRevision"] += 1
            elif tamper == "owner":
                history["ownerSubject"] = "other_owner"
            else:
                candidate["registryHistory"][0] = candidate["registryHistory"][1]
            with (
                self.subTest(tamper=tamper),
                self.assertRaisesRegex(ContractError, "authorization_unavailable"),
            ):
                verify_legacy_archive_history(candidate, self.registry, history)

    def test_transfer_verifier_accepts_retained_receipts_beyond_the_legacy_limit(self):
        item = self.apply(
            "recovery_authorize",
            1000,
            authorizationId="old_recovery_approval",
            newArchiveDigest="a" * 64,
        )
        vault = deepcopy(self.vault)
        registry = self.registry
        for _ in range(31):
            bundle = self.f.make_bundle(previous=registry)
            registry = self.f.verify(bundle, previous=registry)
            vault["registryHistory"].append(bundle)
        cursor = PrivateRegistryCursor(registry, 2)
        with self.assertRaisesRegex(ContractError, "authorization_unavailable"):
            verify_legacy_archive_history(vault, registry, self.row)
        checked = verify_transferred_archive_history(vault, cursor, self.row)
        self.assertEqual(checked["operations"][item["receipt"]["operationId"]], item)
        with self.assertRaisesRegex(ContractError, "authorization_unavailable"):
            verify_transferred_archive_history(vault, PrivateRegistryCursor(registry, 1), self.row)
        vault["registryHistory"][16] = vault["registryHistory"][15]
        with self.assertRaisesRegex(ContractError, "authorization_unavailable"):
            verify_transferred_archive_history(vault, cursor, self.row)

    def test_absent_initial_archive_cannot_be_reported_as_a_verified_deletion(self):
        vault = {**self.vault, "archive": None}
        with self.assertRaisesRegex(ContractError, "authorization_unavailable"):
            verify_legacy_archive_history(vault, self.registry, None)
        self.apply("archive_delete", 1000)
        result = verify_legacy_archive_history(vault, self.registry, self.row)
        self.assertEqual(result, self.state)
        self.assertTrue(result["deleted"])
        self.assertEqual(result["revision"], 1)

    def test_retired_ciphertext_still_requires_exact_signed_transfer_and_history(self):
        self.apply(
            "recovery_authorize",
            1000,
            authorizationId="recovery",
            newArchiveDigest="f" * 64,
        )
        previous = PrivateRegistryCursor(self.registry, 1).head()
        first = self.f.make_bundle(previous=self.registry, issued_at=1050)
        after = self.f.verify(first, previous=self.registry, now=1100)
        change = {
            **self.scope,
            "contractVersion": CONTRACT_VERSION,
            "profile": "folioview.owner-registry-transition.v1",
            "operationId": "synthetic_registry_transfer_01",
            "previousVaultVersion": 2,
            "nextVaultVersion": 3,
            "previousHead": previous,
            "nextHead": PrivateRegistryCursor(after, 2).head(),
            "archive": {
                "state": "active",
                "digest": self.state["digest"],
                "version": 2,
            },
            "issuedAt": 1050,
            "ownerKeyIds": sorted(after.active_key_ids),
        }
        signed = self.f.sign(change, "root")
        vault = {**self.vault, "archive": None}
        trusted = signing_input_fingerprint(signed)

        def checked(row, signature=signed):
            return verify_retired_archive_history(
                vault, self.registry, row, signature, fingerprint=trusted, now=1100
            )

        self.assertEqual(checked(self.row), self.state)
        bad = deepcopy(self.row)
        bad["history"][0]["receipt"]["archiveRevision"] += 1
        for changed in (None, bad):
            with self.assertRaises(ContractError):
                checked(changed)
        with self.assertRaises(ContractError):
            checked(self.row, self.f.sign({**change, "issuedAt": 1051}, "root"))
        with self.assertRaises(ContractError):
            verify_legacy_archive_history(vault, self.registry, self.row)
