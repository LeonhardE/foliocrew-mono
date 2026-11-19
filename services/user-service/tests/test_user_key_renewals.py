"""Check the atomic same-Root renewal on the User writer after transfer."""

import unittest
from unittest.mock import patch

import test_registry_transition as fixture
from jwcrypto import jwk
from test_private_recovery import OWNER, UID, VAULT

from app.private_resources.authority_cutover import UserAuthorityCutover
from app.private_resources.authority_views import PrivateAuthorityViews
from app.private_resources.key_renewals import PrivateKeyRenewals
from app.private_resources.legacy_baselines import LegacyVaultBaselines, _sha, verified_baseline
from app.private_resources.registry_pages import RegistryHistory
from folioview_shared.encrypted.authority import verify_registry
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import jwk_thumbprint, signing_input_fingerprint, verify_jws
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import b64url_encode, canonical_json
from folioview_shared.encrypted.key_renewal import (
    PROFILE,
    owner_renewal_receipt,
    owner_renewal_response,
)
from folioview_shared.encrypted.legacy_archive import PROFILE as ARCHIVE_PROFILE
from folioview_shared.encrypted.legacy_archive import (
    advance_legacy_archive,
    legacy_archive_receipt,
    verify_legacy_archive_history,
)
from folioview_shared.encrypted.private_resources import PrivateRegistryCursor

OPERATION = "synthetic_user_key_renewal_once"


def digest(value):
    return _sha(canonical_json(value))


class UserKeyRenewalTests(unittest.TestCase):
    def setUp(self):
        sample = fixture.RegistryTransitionTests()
        sample.setUp()
        self.addCleanup(sample.doCleanups)
        self.sample = sample
        cutover = UserAuthorityCutover(sample.store)
        sample.stage_frozen_scope()
        cutover.install(UID, VAULT, sample.packet, now=1000)
        self.now = 1000
        self.service = PrivateKeyRenewals(sample.store, clock=lambda: self.now)
        self.overview = self.service.overview(UID, VAULT)
        self.packet = self.build_packet(
            self.sample, self.overview, self.sample.packet["firstBundle"]
        )

    @staticmethod
    def build_packet(sample, initial, first):
        root = sample.vault["rootJwk"]

        def payload(signed):
            return verify_jws(signed, root, typ="fv-control+jws")

        old = {
            cert["role"]: cert for cert in (payload(row["certificate"]) for row in first["entries"])
        }["recovery_enc"]
        new_key = jwk.JWK.generate(kty="EC", crv="P-256").export(private_key=False, as_dict=True)
        successor = {
            **old,
            "publicJwk": new_key,
            "keyId": jwk_thumbprint(new_key),
            "certificateId": "synthetic_recovery_successor",
            "keyEpoch": old["keyEpoch"] + 1,
            "notBefore": 1000,
            "expiresAt": old["expiresAt"] + 20_000,
        }
        entries = [
            {
                "certificate": row["certificate"],
                "active": payload(row["certificate"])["keyId"] != old["keyId"],
            }
            for row in first["entries"]
        ] + [{"certificate": sample.sign(successor), "active": True}]
        descriptions = [
            {
                "certificateId": cert["certificateId"],
                "payloadDigest": digest(cert),
                "active": row["active"],
            }
            for row in entries
            for cert in [payload(row["certificate"])]
        ]
        checkpoint = {
            **payload(first["checkpoint"]),
            "registrySequence": initial["registrySequence"] + 1,
            "previousDigest": initial["checkpointDigest"],
            "issuedAt": 1000,
            "entriesDigest": digest(sorted(descriptions, key=lambda row: row["certificateId"])),
            "revokedKeyIds": [old["keyId"]],
        }
        bundle = {
            "contractVersion": CONTRACT_VERSION,
            "entries": entries,
            "checkpoint": sample.sign(checkpoint),
        }
        replacement = {
            **sample.vault["archive"],
            "iv": b64url_encode(bytes(range(12))),
            "ciphertext": b64url_encode(bytes(range(16, 44))),
        }
        base = {
            **sample.scope,
            "contractVersion": CONTRACT_VERSION,
            "stableOperationId": OPERATION,
            "expectedVaultVersion": initial["vaultVersion"],
            "registrySequence": initial["registrySequence"],
            "checkpointDigest": initial["checkpointDigest"],
            "keyEpoch": initial["keyEpoch"],
            "expectedLifecycleVersion": initial["lifecycleVersion"],
            "expectedArchiveRevision": initial["archiveRevision"],
            "expectedArchiveDigest": initial["archiveDigest"],
            "newArchiveDigest": digest(replacement),
            "issuedAt": 1000,
            "expiresAt": 1030,
        }
        archive_control = sample.sign(
            {
                **base,
                "profile": ARCHIVE_PROFILE,
                "action": "archive_replace",
                "mode": "rewrap",
                "authorizationId": None,
            }
        )
        control = sample.sign(
            {
                **base,
                "profile": PROFILE,
                "action": "key_renewal",
                "newCheckpointDigest": digest(checkpoint),
                "archiveCommandFingerprint": signing_input_fingerprint(archive_control),
                "renewals": [
                    {
                        "role": old["role"],
                        "principalId": old["principalId"],
                        "priorKeyId": old["keyId"],
                        "newKeyId": successor["keyId"],
                        "priorKeyEpoch": old["keyEpoch"],
                        "newKeyEpoch": successor["keyEpoch"],
                    },
                ],
            }
        )
        return control, archive_control, replacement, bundle

    def test_archive_registry_and_receipt_commit_together_and_replay_after_expiry(self):
        original = self.overview
        result = self.service.renew(UID, VAULT, OPERATION, *self.packet)
        state = self.service.overview(UID, VAULT)
        self.assertEqual(state["vaultVersion"], original["vaultVersion"] + 1)
        self.assertEqual(state["registrySequence"], original["registrySequence"] + 1)
        self.assertEqual(state["lifecycleVersion"], original["lifecycleVersion"] + 1)
        self.assertEqual(result["receipt"]["archiveDigest"], state["archiveDigest"])
        read = PrivateAuthorityViews(self.sample.store).owner_current(
            UID, "synthetic_current_renewal_nonce", now=self.now
        )
        self.assertEqual(read["vault"]["archive"], self.packet[2])
        self.assertEqual(read["proof"]["archiveLifecycle"]["state"]["archiveRevision"], 1)
        self.now = 1100
        self.assertEqual(self.service.receipt(UID, VAULT, OPERATION), result)
        self.assertEqual(self.service.renew(UID, VAULT, OPERATION, *self.packet), result)

    def test_rejects_an_expired_or_interrupted_commit_without_advancing(self):
        self.now = 1030
        with self.assertRaisesRegex(ContractError, "key_authorization_required"):
            self.service.renew(UID, VAULT, OPERATION, *self.packet)
        self.now = 1000
        with patch.object(
            self.service.cutover, "_transaction", wraps=self.service.cutover._transaction
        ) as tx:
            original = tx._mock_wraps

            def interrupt(callback, *, writes, **options):
                if writes:
                    raise ContractError("version_conflict")
                return original(callback, writes=writes, **options)

            tx.side_effect = interrupt
            with self.assertRaisesRegex(ContractError, "version_conflict"):
                self.service.renew(UID, VAULT, OPERATION, *self.packet)
        self.assertEqual(self.service.overview(UID, VAULT), self.overview)
        with self.assertRaisesRegex(ContractError, "not_found"):
            self.service.receipt(UID, VAULT, OPERATION)
        with self.assertRaisesRegex(ContractError, "not_found"):
            self.service.renew("another-account", VAULT, OPERATION, *self.packet)

    def test_legacy_renewal_receipt_from_the_original_operation_baseline(self):
        sample = fixture.RegistryTransitionTests()
        sample.setUp()
        self.addCleanup(sample.doCleanups)
        original = sample.vault
        root = original["rootJwk"]
        first = original["registryHistory"][0]

        def signed_payload(signed):
            return verify_jws(signed, root, typ="fv-control+jws")

        def registry(bundle, previous=None):
            return verify_registry(
                bundle,
                root_jwk=root,
                pinned_root_key_id=original["rootKeyId"],
                owner_subject=OWNER,
                vault_id=VAULT,
                now=1000,
                previous=previous,
            )

        before = registry(first)
        control, archive_control, replacement, second = self.build_packet(
            sample,
            {
                "vaultVersion": 1,
                "registrySequence": 1,
                "checkpointDigest": before.checkpoint_digest,
                "keyEpoch": before.key_epoch,
                "lifecycleVersion": 0,
                "archiveRevision": 0,
                "archiveDigest": digest(original["archive"]),
            },
            first,
        )
        renewed = registry(second, previous=before)
        previous = PrivateRegistryCursor(renewed, 1)
        RegistryHistory(sample.heads).stage(second, root_jwk=root, cursor=previous)
        state = verify_legacy_archive_history(original, before, None)
        archive_command = signed_payload(archive_control)
        changed = advance_legacy_archive(state, archive_command, archive_control, 1000)
        lifecycle = {
            **sample.scope,
            "initialArchiveDigest": state["digest"],
            "history": [
                {
                    "command": archive_control,
                    "receipt": legacy_archive_receipt(
                        original, archive_command, changed, archive_control, 1000
                    ),
                }
            ],
        }
        previous_vault = {
            **original,
            "registryHistory": [first, second],
            "version": 2,
            "operationCount": 2,
            "archive": replacement,
        }
        baseline = _sha(verified_baseline(OWNER, previous_vault, lifecycle, now=1000))
        LegacyVaultBaselines(sample.store).stage(
            OWNER, previous_vault, lifecycle, expected_digest=baseline, now=1000
        )
        receipt = owner_renewal_receipt(
            original, signed_payload(control), renewed, changed, control, 1000
        )
        record = {
            **sample.scope,
            "profile": PROFILE,
            "command": control,
            "archiveCommand": archive_control,
            "receipt": receipt,
        }

        def field(value):
            if type(value) is dict:
                return {"mapValue": {"fields": {key: field(val) for key, val in value.items()}}}
            if type(value) is list:
                return {"arrayValue": {"values": [field(item) for item in value]}}
            if type(value) is int:
                return {"integerValue": str(value)}
            return {"stringValue": value}

        original_path = "hub_operations/" + digest([OWNER, "key-renewal", OPERATION])
        sample.vault = previous_vault
        cutover = UserAuthorityCutover(sample.store)
        sample.stage_frozen_scope(
            baselineDigest=baseline,
            extra_operations={original_path: {key: field(value) for key, value in record.items()}},
        )
        entries = [entry for entry in second["entries"] if entry["active"]]
        descriptions = [
            {"certificateId": cert["certificateId"], "payloadDigest": digest(cert), "active": True}
            for entry in entries
            for cert in [signed_payload(entry["certificate"])]
        ]
        checkpoint = {
            **signed_payload(second["checkpoint"]),
            "registrySequence": 3,
            "previousDigest": renewed.checkpoint_digest,
            "revokedKeyIds": [],
            "entriesDigest": digest(sorted(descriptions, key=lambda item: item["certificateId"])),
        }
        first_user = {
            "contractVersion": CONTRACT_VERSION,
            "entries": entries,
            "checkpoint": sample.sign(checkpoint),
        }
        current = registry(first_user)
        transition = {
            **sample.transition,
            "previousHead": previous.head(),
            "nextHead": PrivateRegistryCursor(current, 2).head(),
            "previousVaultVersion": 2,
            "nextVaultVersion": 3,
            "ownerKeyIds": sorted(current.active_key_ids),
            "archive": {"state": "active", "version": 2, "digest": changed["digest"]},
        }
        cutover.install(
            UID,
            VAULT,
            {
                **sample.packet,
                "signedTransition": sample.sign(transition),
                "firstBundle": first_user,
            },
            now=1000,
        )
        service = PrivateKeyRenewals(sample.store, clock=lambda: 1100)
        expected = owner_renewal_response(receipt)
        self.assertEqual(service.receipt(UID, VAULT, OPERATION), expected)
        self.assertEqual(
            service.renew(UID, VAULT, OPERATION, control, archive_control, replacement, second),
            expected,
        )
        self.assertEqual(service.overview(UID, VAULT)["registrySequence"], 3)
