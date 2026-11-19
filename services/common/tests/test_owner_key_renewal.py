"""Check the signed renewal contract shared by Hub and User."""

import unittest

from test_encrypted_authority import AuthorityFixture

from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import signing_input_fingerprint
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.key_renewal import (
    PROFILE,
    owner_renewal_receipt,
    require_fresh_renewal_keys,
    verify_owner_renewal_archive,
    verify_owner_renewal_command,
    verify_owner_renewal_delta,
)
from folioview_shared.encrypted.legacy_archive import PROFILE as ARCHIVE_PROFILE


class OwnerKeyRenewalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = f = AuthorityFixture()
        self.row = {
            "ownerSubject": f.owner,
            "vaultId": f.vault,
            "rootKeyId": f.root_id,
            "rootJwk": f.root_public,
        }
        prior = f.certificates["recovery_enc"]
        successor = f.add_key("successor", prior["role"], prior["principalId"], epoch=2)
        successor.update(notBefore=1000, expiresAt=7000)
        bundle = f.make_bundle(previous=f.registry, revoked=("recovery_enc",), issued_at=1000)
        self.registry = f.verify(bundle, previous=f.registry)
        base = {
            **{k: v for k, v in self.row.items() if k != "rootJwk"},
            "contractVersion": CONTRACT_VERSION,
            "stableOperationId": "synthetic_shared_renewal_operation",
            "expectedVaultVersion": 3,
            "registrySequence": f.registry.registry_sequence,
            "checkpointDigest": f.registry.checkpoint_digest,
            "keyEpoch": f.registry.key_epoch,
            "expectedLifecycleVersion": 1,
            "expectedArchiveRevision": 0,
            "expectedArchiveDigest": "a" * 64,
            "newArchiveDigest": "b" * 64,
            "issuedAt": 1000,
            "expiresAt": 1050,
        }
        self.archive = {
            **base,
            "profile": ARCHIVE_PROFILE,
            "action": "archive_replace",
            "mode": "rewrap",
            "authorizationId": None,
        }
        self.archive_command = f.sign(self.archive, "root")
        self.renewal = {
            **base,
            "profile": PROFILE,
            "action": "key_renewal",
            "newCheckpointDigest": self.registry.checkpoint_digest,
            "archiveCommandFingerprint": signing_input_fingerprint(self.archive_command),
            "renewals": [
                {
                    "role": prior["role"],
                    "principalId": prior["principalId"],
                    "priorKeyId": prior["keyId"],
                    "newKeyId": successor["keyId"],
                    "priorKeyEpoch": 1,
                    "newKeyEpoch": 2,
                },
            ],
        }

    def test_root_pair_exact_delta_and_receipt(self):
        f = self.fixture
        signed = f.sign(self.renewal, "root")
        payload = verify_owner_renewal_command(signed, self.row)
        self.assertEqual(
            verify_owner_renewal_archive(payload, self.archive_command, self.row), self.archive
        )
        require_fresh_renewal_keys(payload, [f.registry])
        verify_owner_renewal_delta(payload, f.registry, self.registry, 1000)
        state = {"version": 2, "revision": 1, "digest": payload["newArchiveDigest"]}
        receipt = owner_renewal_receipt(self.row, payload, self.registry, state, signed, 1000)
        self.assertEqual(receipt["vaultVersion"], 4)
        self.assertEqual(
            receipt["archiveCommandFingerprint"], signing_input_fingerprint(self.archive_command)
        )
        self.assertEqual(receipt["checkpointDigest"], self.registry.checkpoint_digest)

    def test_refuses_another_signer_pair_and_prior_successor_key(self):
        f = self.fixture
        with self.assertRaises(ContractError):
            verify_owner_renewal_command(f.sign(self.renewal), self.row)
        foreign_archive = f.sign({**self.archive, "newArchiveDigest": "c" * 64}, "root")
        with self.assertRaisesRegex(ContractError, "recipient_binding_mismatch"):
            verify_owner_renewal_archive(self.renewal, foreign_archive, self.row)
        with self.assertRaisesRegex(ContractError, "registry_conflict"):
            require_fresh_renewal_keys(self.renewal, [self.registry])
        wrong_head = {**self.renewal, "newCheckpointDigest": "d" * 64}
        with self.assertRaisesRegex(ContractError, "registry_conflict"):
            verify_owner_renewal_delta(wrong_head, f.registry, self.registry, 1000)
