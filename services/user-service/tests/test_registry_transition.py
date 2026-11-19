"""A new signed registry must anchor the owner, old chain, and existing archive."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from jwcrypto import jwk
from test_private_recovery import OWNER, UID, VAULT, registry_fixture

from app.private_resources.legacy_baselines import LegacyVaultBaselines, verified_baseline
from app.private_resources.recovery import RecoveryHeads
from app.private_resources.registry_pages import COLLECTION, RegistryHistory
from app.private_resources.registry_transition import UserRegistryTransition
from app.resources import SQLiteUserResourceStore
from folioview_shared.encrypted.authority import verify_registry
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import jwk_thumbprint, sign_jws, verify_jws
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import b64url_encode, canonical_json
from folioview_shared.encrypted.private_resources import PrivateRegistryCursor


def digest(value):
    return hashlib.sha256(canonical_json(value)).hexdigest()


class RegistryTransitionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = SQLiteUserResourceStore(str(Path(folder.name) / "original.sqlite"))
        self.root, public, scope, base, bundle, _ = registry_fixture()
        self.scope = {"ownerSubject": OWNER, "vaultId": VAULT, "rootKeyId": base.root_key_id}
        recovery = jwk.JWK.generate(kty="EC", crv="P-256").export(private_key=False, as_dict=True)
        certificate = {
            **scope,
            "artifactType": "key_certificate",
            "certificateId": "recovery_fixture",
            "keyId": jwk_thumbprint(recovery),
            "issuerKeyId": base.root_key_id,
            "publicJwk": recovery,
            "role": "recovery_enc",
            "principalId": "recovery_fixture",
            "connectionId": None,
            "keyEpoch": 1,
            "notBefore": 200,
            "expiresAt": 1020,
            "capabilities": [],
        }
        bundle["entries"].append({"certificate": self.sign(certificate), "active": True})
        checkpoint = verify_jws(bundle["checkpoint"], public, typ="fv-control+jws")
        descriptions = []
        for entry in bundle["entries"]:
            prior = verify_jws(entry["certificate"], public, typ="fv-control+jws")
            descriptions.append(
                {
                    "certificateId": prior["certificateId"],
                    "payloadDigest": digest(prior),
                    "active": True,
                }
            )
        checkpoint["entriesDigest"] = digest(
            sorted(descriptions, key=lambda row: row["certificateId"])
        )
        bundle["checkpoint"] = self.sign(checkpoint)
        args = dict(
            root_jwk=public,
            pinned_root_key_id=base.root_key_id,
            owner_subject=OWNER,
            vault_id=VAULT,
            now=1000,
        )
        original = verify_registry(bundle, **args)
        previous = PrivateRegistryCursor(original, 1)
        self.heads = RecoveryHeads(self.store)
        RegistryHistory(self.heads).stage(bundle, root_jwk=public, cursor=previous)
        archive = {
            **self.scope,
            "profile": "folioview.passkey-vault.v1",
            "credentialId": b64url_encode(b"existing-fake-credential"),
            "prfSalt": b64url_encode(b"b" * 32),
            "iv": b64url_encode(b"c" * 12),
            "ciphertext": b64url_encode(b"synthetic-encrypted-original"),
        }
        vault = {
            **self.scope,
            "rootJwk": public,
            "registryHistory": [bundle],
            "archive": archive,
            "version": 1,
            "operationCount": 1,
            "sources": [],
        }
        prepared = verified_baseline(OWNER, vault, None, now=1000)
        self.digest = hashlib.sha256(prepared).hexdigest()
        LegacyVaultBaselines(self.store).stage(
            OWNER, vault, None, expected_digest=self.digest, now=1000
        )
        new_bundle = {
            **bundle,
            "checkpoint": self.sign(
                {
                    **checkpoint,
                    "registrySequence": 2,
                    "previousDigest": original.checkpoint_digest,
                    "issuedAt": 1000,
                }
            ),
        }
        current = verify_registry(new_bundle, **args, previous=original)
        self.transition = {
            **self.scope,
            "contractVersion": CONTRACT_VERSION,
            "profile": "folioview.owner-registry-transition.v1",
            "operationId": "synthetic_registry_transition_0001",
            "previousVaultVersion": 1,
            "nextVaultVersion": 2,
            "previousHead": previous.head(),
            "nextHead": PrivateRegistryCursor(current, 2).head(),
            "ownerKeyIds": sorted(current.active_key_ids),
            "issuedAt": 1000,
            "archive": {"state": "active", "version": 1, "digest": digest(archive)},
        }
        self.packet = {
            "operationId": self.transition["operationId"],
            "signedTransition": self.sign(self.transition),
            "firstBundle": new_bundle,
        }
        self.service = UserRegistryTransition(self.store)

    def sign(self, value):
        return sign_jws(value, self.root, typ="fv-control+jws")

    def test_signatures_validate_without_changing_active_state(self):
        accepted = self.service.verify_candidate(UID, VAULT, self.digest, self.packet, now=1000)
        self.assertEqual(accepted["registryStart"], self.transition["nextHead"])
        self.assertEqual(accepted["operationId"], self.packet["operationId"])
        self.assertEqual(
            self.service.verify_candidate(UID, VAULT, self.digest, self.packet, now=1000), accepted
        )
        self.assertIsNone(self.heads.read(OWNER))

    def test_well_signed_wrong_archive_unknown_owner_and_missing_original_history_are_refused(self):
        changed = self.sign(
            {**self.transition, "archive": {**self.transition["archive"], "digest": "f" * 64}}
        )
        with self.assertRaisesRegex(ContractError, "version_conflict"):
            self.service.verify_candidate(
                UID, VAULT, self.digest, {**self.packet, "signedTransition": changed}, now=1000
            )
        with self.assertRaisesRegex(ContractError, "not_found"):
            self.service.verify_candidate("foreign", VAULT, self.digest, self.packet, now=1000)
        with self.store.connection() as db:
            db.execute(f"DELETE FROM {COLLECTION}")
        with self.assertRaisesRegex(ContractError, "authorization_unavailable"):
            self.service.verify_candidate(UID, VAULT, self.digest, self.packet, now=1000)
