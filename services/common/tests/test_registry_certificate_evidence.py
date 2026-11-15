"""Owned static evidence preserves exact signatures and every dynamic history check."""

import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from test_encrypted_authority import AuthorityFixture
from test_registry_certificate_memo import retain_certificates

from folioview_shared.encrypted import authority
from folioview_shared.encrypted.authority import RegistryCertificateMemo
from folioview_shared.encrypted.crypto import verify_jws
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json


class RegistryCertificateEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.f = AuthorityFixture()
        self.memo = RegistryCertificateMemo()

    def history(self, count=3):
        bundles, previous = [self.f.bundle], self.f.registry
        for _ in range(count - 1):
            bundle = retain_certificates(self.f.make_bundle(previous=previous), bundles[-1])
            previous = self.f.verify(bundle, previous=previous)
            bundles.append(bundle)
        return bundles

    def verify_history(self, bundles, memo):
        previous = None
        for bundle in bundles:
            previous = self.f.verify(bundle, previous=previous, signature_memo=memo)
        return previous

    def test_only_owned_successful_payloads_skip_repeated_canonicalization(self):
        bundles = self.history()
        counts = []
        for memo in (None, self.memo):
            with patch.object(authority, "canonical_json", wraps=canonical_json) as encode:
                result = self.verify_history(bundles, memo)
            counts.append(
                sum(
                    type(call.args[0]) is dict
                    and call.args[0].get("artifactType") == "key_certificate"
                    for call in encode.call_args_list
                )
            )
            self.assertEqual(result, self.verify_history(bundles, None))
        # Seven unique payloads, versus 21 digests and 28 prior-payload comparisons.
        self.assertEqual(counts, [49, 7])

    def test_shared_payload_identity_never_reuses_active_or_revoked_decisions(self):
        first = self.f.verify(self.f.bundle, signature_memo=self.memo)
        bundle = retain_certificates(
            self.f.make_bundle(previous=first, revoked=("A1_sig",)), self.f.bundle
        )
        second = self.f.verify(bundle, previous=first, signature_memo=self.memo)
        kid = self.f.kid("A1_sig")
        self.assertIs(first.certificates[kid], second.certificates[kid])
        self.assertIn(kid, first.active_key_ids)
        self.assertNotIn(kid, second.active_key_ids)
        self.assertIn(kid, second.revoked_key_ids)
        self.assertEqual(self.f.certificates["A1_sig"], first.cert(kid, now=1000))
        with self.assertRaises(ContractError):
            second.cert(kid, now=1000)
        with self.assertRaises(ContractError):
            first.cert(kid, now=5000)

    def test_same_payload_with_different_jws_reverifies_and_compares_prior_payload(
        self,
    ):
        first = self.f.verify(self.f.bundle, signature_memo=self.memo)
        second_bundle = self.f.make_bundle(previous=first)
        self.assertTrue(
            all(
                old["certificate"]["signature"] != new["certificate"]["signature"]
                for old, new in zip(self.f.bundle["entries"], second_bundle["entries"], strict=True)
            )
        )
        with (
            patch.object(authority, "verify_jws", wraps=verify_jws) as verify,
            patch.object(authority, "canonical_json", wraps=canonical_json) as encode,
        ):
            second = self.f.verify(second_bundle, previous=first, signature_memo=self.memo)
        self.assertEqual(verify.call_count, 8)  # Seven new JWS plus the checkpoint.
        self.assertEqual(
            14,
            sum(
                type(call.args[0]) is dict and call.args[0].get("artifactType") == "key_certificate"
                for call in encode.call_args_list
            ),
        )  # Seven new canonical payloads plus seven prior payloads.
        self.assertEqual(second, self.f.verify(second_bundle, previous=first))
        self.assertIsNot(
            first.certificates[self.f.kid("device_sig")],
            second.certificates[self.f.kid("device_sig")],
        )

    def test_same_key_changed_root_signed_payload_still_conflicts_on_static_hit(self):
        first = self.f.verify(self.f.bundle, signature_memo=self.memo)
        self.f.certificates["device_sig"]["principalId"] = "changed_principal"
        bundle = retain_certificates(self.f.make_bundle(previous=first), self.f.bundle)
        self.memo._certificate(
            bundle["entries"][0]["certificate"],
            self.f.root_public,
            expected_kid=self.f.root_id,
        )
        for memo in (None, self.memo, self.memo):
            with (
                self.subTest(memo=memo is not None),
                self.assertRaises(ContractError) as error,
            ):
                self.f.verify(bundle, previous=first, signature_memo=memo)
            self.assertEqual(error.exception.code, "registry_conflict")

    def test_prepared_root_snapshot_and_closed_jws_map_bind_complete_inputs(self):
        root = copy.deepcopy(self.f.root_public)
        check = self.memo._registry_certificates(root, expected_kid=self.f.root_id)
        root.update(AuthorityFixture().root_public)
        signed = self.f.bundle["entries"][0]["certificate"]
        self.assertEqual(authority._thaw(check(signed).payload), self.f.certificates["device_sig"])
        for candidate in (signed | {"extra": True}, signed | {"signature": None}, {}):
            with (
                self.subTest(candidate_fields=tuple(candidate)),
                self.assertRaises(ContractError),
            ):
                check(candidate)
        # An otherwise identical Root with extra bytes cannot borrow a valid hit.
        for _ in range(2):
            with self.assertRaises(ContractError):
                self.memo._certificate(
                    signed,
                    self.f.root_public | {"extra": "same-thumbprint-different-root"},
                    expected_kid=self.f.root_id,
                )

    def test_proofs_have_no_public_constructor_and_all_legacy_views_are_copies(self):
        registry = self.f.verify(self.f.bundle, signature_memo=self.memo)
        kid = self.f.kid("device_sig")
        proof = registry.certificates[kid]
        with self.assertRaises(TypeError):
            authority._CertificatePayload()
        with self.assertRaises(TypeError):
            authority._CertificatePayload({"unverified": True})
        with self.assertRaises(TypeError):
            proof["principalId"] = "forged"
        with self.assertRaises(TypeError):
            proof["publicJwk"]["x"] = "forged"
        with self.assertRaises(AttributeError):
            proof.canonical = b"forged"
        with self.assertRaises(AttributeError):
            proof.digest = "0" * 64
        for slot in ("__value", "__canonical", "__digest"):
            with self.subTest(slot=slot), self.assertRaises(AttributeError):
                delattr(proof, "_CertificatePayload" + slot)
        signed = self.f.bundle["entries"][0]["certificate"]
        clone, _ = self.memo._certificate(signed, self.f.root_public, expected_kid=self.f.root_id)
        clone["capabilities"].clear()
        clone["publicJwk"]["x"] = "forged"
        generic = self.memo._verify(
            signed,
            self.f.root_public,
            typ="fv-control+jws",
            expected_kid=self.f.root_id,
        )
        generic["principalId"] = "forged"
        selected = registry.cert(kid, now=1000)
        self.assertEqual(selected, self.f.certificates["device_sig"])
        selected["capabilities"].clear()
        self.assertEqual(registry.cert(kid, now=1000), self.f.certificates["device_sig"])
        # A payload object supplied as a signed object cannot install evidence.
        with self.assertRaises(ContractError):
            self.memo._certificate(proof, self.f.root_public, expected_kid=self.f.root_id)

    def test_no_memo_mixed_histories_and_separate_operations_are_equivalent(self):
        bundles = self.history()
        expected = self.verify_history(bundles, None)
        first = self.f.verify(bundles[0])
        second = self.f.verify(bundles[1], previous=first, signature_memo=self.memo)
        self.assertEqual(self.f.verify(bundles[2], previous=second), expected)
        other = self.verify_history(bundles, RegistryCertificateMemo())
        reused = self.verify_history(bundles, self.memo)
        self.assertEqual(other, reused)
        self.assertIsNot(
            other.certificates[self.f.kid("device_sig")],
            reused.certificates[self.f.kid("device_sig")],
        )

    def test_parallel_histories_share_only_static_evidence_not_authority(self):
        revoked = retain_certificates(self.f.make_bundle(revoked=("A1_sig",)), self.f.bundle)
        with (
            patch.object(authority, "verify_jws", wraps=verify_jws) as verify,
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            active = pool.submit(self.f.verify, self.f.bundle, signature_memo=self.memo)
            removed = pool.submit(self.f.verify, revoked, signature_memo=self.memo)
            active, removed = active.result(timeout=5), removed.result(timeout=5)
        self.assertEqual(
            2,
            sum(
                call.args[0] in (self.f.bundle["checkpoint"], revoked["checkpoint"])
                for call in verify.call_args_list
            ),
        )
        kid = self.f.kid("A1_sig")
        self.assertEqual(active.cert(kid, now=1000), self.f.certificates["A1_sig"])
        with self.assertRaises(ContractError):
            removed.cert(kid, now=1000)

    def test_checkpoint_and_certificate_checks_use_the_same_private_root_snapshot(self):
        original, foreign = (
            copy.deepcopy(self.f.root_public),
            AuthorityFixture().root_public,
        )
        expected = self.f.verify(self.f.bundle)

        def mutate(signed, public_jwk, **options):
            original.update(foreign)
            return verify_jws(signed, public_jwk, **options)

        with patch.object(authority, "verify_jws", side_effect=mutate):
            self.assertEqual(
                self.f.verify(self.f.bundle, root_jwk=original, signature_memo=self.memo),
                expected,
            )
        with self.assertRaises(ContractError):
            self.f.verify(self.f.bundle, root_jwk=original, signature_memo=self.memo)


if __name__ == "__main__":
    unittest.main()
