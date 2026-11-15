"""Explicit large-history formats with offline synthetic Root-signed chains."""

import copy
import unittest
from unittest.mock import patch

from test_encrypted_authority import AuthorityFixture

from folioview_shared.encrypted.authority import RegistryCertificateMemo
from folioview_shared.encrypted.constants import MAX_READ_BYTES, MAX_STORED_DOCUMENT_BYTES
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import b64url_decode, b64url_encode, canonical_json
from folioview_shared.encrypted.reference_history import (
    REFERENCE_HISTORY_FORMAT,
    decode_reference_history,
    encode_reference_history,
)
from folioview_shared.encrypted.reference_history_v2 import (
    MAX_EXPANDED_HISTORY_BYTES,
    STORAGE_HISTORY_V2_FORMAT,
    TRANSPORT_HISTORY_FORMAT,
    decode_storage_history_v2,
    decode_transport_history,
    encode_storage_history_v2,
    encode_transport_history,
    snapshot_registry_history,
)


class ExtendedHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        f = AuthorityFixture(owner="owner_" + "a" * 64, vault="vault_" + "b" * 32)
        f.certificates = {name: cert for name, cert in f.certificates.items() if "A" not in name}
        history, known, previous = [], {}, None
        memo = RegistryCertificateMemo()
        for generation in range(32):
            if 0 < generation < 31:
                principal = f"synthetic_{generation}"
                for role in ("agent_sig", "agent_enc"):
                    f.add_key(f"{principal}_{role}", role, principal, f"connection_{generation}")
            revoked = ("synthetic_1_agent_sig",) if generation == 31 else ()
            bundle = f.make_bundle(previous=previous, revoked=revoked)
            for entry in bundle["entries"]:
                signed = entry["certificate"]
                known.setdefault(signed["payload"], signed)
                entry["certificate"] = copy.deepcopy(known[signed["payload"]])
            previous = f.verify(bundle, previous=previous, signature_memo=memo)
            history.append(bundle)
        cls.f, cls.history = f, history
        cls.storage = encode_storage_history_v2(history)
        cls.transport = encode_transport_history(history)

    def assert_code(self, code, call, *args, **kwargs):
        with self.assertRaises(ContractError) as raised:
            call(*args, **kwargs)
        self.assertEqual(code, raised.exception.code)

    def verify(self, history, **kwargs):
        previous, memo = None, RegistryCertificateMemo()
        for bundle in history:
            previous = self.f.verify(bundle, previous=previous, signature_memo=memo, **kwargs)
        return previous

    def test_28_31_32_valid_histories_roundtrip_with_identical_full_authority(self):
        for count in (28, 31, 32):
            original = self.history[:count]
            with self.subTest(generations=count):
                self.assertGreater(len(canonical_json(original)), MAX_READ_BYTES)
                self.assertLess(len(canonical_json(original)), MAX_EXPANDED_HISTORY_BYTES)
                baseline = self.verify(original)
                for encode, decode, profile in (
                    (
                        encode_storage_history_v2,
                        decode_storage_history_v2,
                        STORAGE_HISTORY_V2_FORMAT,
                    ),
                    (encode_transport_history, decode_transport_history, TRANSPORT_HISTORY_FORMAT),
                ):
                    compact = encode(original)
                    self.assertEqual(profile, compact["format"])
                    self.assertLessEqual(len(canonical_json(compact)), MAX_STORED_DOCUMENT_BYTES)
                    restored = decode(compact)
                    self.assertEqual(canonical_json(original), canonical_json(restored))
                    self.assertEqual(baseline, self.verify(restored))
                self.assertEqual(original, snapshot_registry_history(original))
        self.assertEqual(63, len(self.history[-1]["entries"]))
        self.assertFalse(self.history[-1]["entries"][3]["active"])

    def test_v1_public_api_defaults_and_maximum_are_unchanged(self):
        for function in (encode_reference_history, decode_reference_history):
            self.assert_code("payload_too_large", function, self.history)
            self.assert_code(
                "malformed_request",
                function,
                self.history[:1],
                max_expanded_bytes=MAX_READ_BYTES + 1,
            )
        for value in (self.storage, self.transport, canonical_json(self.storage)):
            self.assert_code("malformed_request", decode_reference_history, value)

    def test_new_storage_reader_keeps_legacy_and_v1_under_old_cap(self):
        small = self.history[:2]
        legacy = encode_reference_history(small)
        for value in (small, canonical_json(small), legacy, canonical_json(legacy)):
            self.assertEqual(small, decode_storage_history_v2(value))
        self.assert_code("payload_too_large", decode_storage_history_v2, self.history)
        # Re-labeling a physically small v2 object cannot grant v2 expansion to v1.
        relabeled = self.storage | {"format": REFERENCE_HISTORY_FORMAT}
        self.assert_code("payload_too_large", decode_storage_history_v2, relabeled)
        self.assert_code("payload_too_large", decode_reference_history, relabeled)

    def test_transport_never_accepts_storage_or_legacy_as_a_fallback(self):
        for value in (
            self.history[:1],
            encode_reference_history(self.history[:1]),
            self.storage,
            canonical_json(self.transport),
            {},
            None,
        ):
            self.assert_code("malformed_request", decode_transport_history, value)
        self.assert_code("malformed_request", decode_storage_history_v2, self.transport)
        self.assert_code(
            "malformed_request", decode_storage_history_v2, canonical_json(self.transport)
        )

    def test_storage_bytes_are_strict_canonical_bounded_and_detached(self):
        raw = canonical_json(self.storage)
        self.assertEqual(self.history, decode_storage_history_v2(raw))
        for value, code in (
            (b" " + raw, "malformed_request"),
            (b"\xef\xbb\xbf" + raw, "malformed_request"),
            (raw[:-1] + b',"format":"unknown"}', "malformed_request"),
            (b" " * (MAX_STORED_DOCUMENT_BYTES + 1), "payload_too_large"),
            (raw.decode(), "malformed_request"),
            (bytearray(raw), "malformed_request"),
        ):
            self.assert_code(code, decode_storage_history_v2, value)

    def test_all_five_helpers_only_allow_strict_tightening_of_the_fixed_cap(self):
        for function, value in (
            (encode_storage_history_v2, self.history[:1]),
            (decode_storage_history_v2, self.storage),
            (encode_transport_history, self.history[:1]),
            (decode_transport_history, self.transport),
            (snapshot_registry_history, self.history[:1]),
        ):
            for invalid in (True, False, 0, -1, 1.0, MAX_EXPANDED_HISTORY_BYTES + 1):
                self.assert_code("malformed_request", function, value, max_expanded_bytes=invalid)

    def test_exact_expanded_budget_is_precomputed_before_copies(self):
        exact = len(canonical_json(self.history))
        for function, value in (
            (encode_storage_history_v2, self.history),
            (decode_storage_history_v2, self.storage),
            (encode_transport_history, self.history),
            (decode_transport_history, self.transport),
            (snapshot_registry_history, self.history),
        ):
            function(value, max_expanded_bytes=exact)
            self.assert_code("payload_too_large", function, value, max_expanded_bytes=exact - 1)
        with patch("folioview_shared.encrypted.reference_history.copy.deepcopy") as clone:
            self.assert_code(
                "payload_too_large",
                decode_storage_history_v2,
                self.storage,
                max_expanded_bytes=exact - 1,
            )
        clone.assert_not_called()

    def test_corruption_ref_types_and_unknown_fields_share_original_strict_rules(self):
        mutations = {
            "unknown format": lambda x: x.update(format="unknown"),
            "extra outer": lambda x: x.update(extra=1),
            "duplicate signed value": lambda x: x["certificates"].append(x["certificates"][0]),
            "unused signed value": lambda x: x["certificates"].append(
                x["certificates"][0] | {"signature": "A" * 86}
            ),
            "extra signed field": lambda x: x["certificates"][0].update(extra=1),
            "bool": lambda x: x["bundles"][0]["entries"][0].__setitem__(0, True),
            "float": lambda x: x["bundles"][0]["entries"][0].__setitem__(0, 0.0),
            "negative": lambda x: x["bundles"][0]["entries"][0].__setitem__(0, -1),
            "hole": lambda x: x["bundles"][0]["entries"][0].__setitem__(0, 1),
            "dangling": lambda x: x["bundles"][0]["entries"][0].__setitem__(0, 2048),
            "bad active": lambda x: x["bundles"][0]["entries"][0].__setitem__(1, 1),
            "template override": lambda x: x["bundles"][0]["bundle"].update(entries=[]),
        }
        for original, decode in (
            (self.storage, decode_storage_history_v2),
            (self.transport, decode_transport_history),
        ):
            for name, change in mutations.items():
                with self.subTest(format=original["format"], corruption=name):
                    value = copy.deepcopy(original)
                    change(value)
                    self.assert_code("malformed_request", decode, value)

    def test_counts_and_per_bundle_limits_are_not_raised_by_the_local_cap(self):
        for encode in (
            encode_storage_history_v2,
            encode_transport_history,
            snapshot_registry_history,
        ):
            self.assert_code("malformed_request", encode, [])
            self.assert_code("malformed_request", encode, self.history + [self.history[-1]])
            history = copy.deepcopy(self.history[:1])
            history[0]["entries"] *= 22  # 66 entries, not a new 64-entry policy.
            self.assert_code("malformed_request", encode, history)
        for original, decode in (
            (self.storage, decode_storage_history_v2),
            (self.transport, decode_transport_history),
        ):
            value = copy.deepcopy(original)
            value["certificates"][0]["payload"] = "a" * 131072
            self.assert_code("payload_too_large", decode, value)

    def test_owned_snapshots_and_each_occurrence_are_independent(self):
        source = copy.deepcopy(self.history)
        encoded = encode_storage_history_v2(source)
        decoded = decode_storage_history_v2(encoded)
        snapshot = snapshot_registry_history(source)
        source[0]["entries"][0]["active"] = False
        encoded["certificates"][0]["signature"] = "A" * 86
        self.assertEqual(self.history, decoded)
        self.assertEqual(self.history, snapshot)
        decoded[0]["entries"][0]["certificate"]["signature"] = "changed"
        self.assertNotEqual(decoded[0]["entries"][0], decoded[1]["entries"][0])
        self.assertEqual(self.history, snapshot)

    def test_larger_local_snapshot_does_not_discard_metadata_or_grant_authority(self):
        history = copy.deepcopy(self.history)
        history[0]["written_at"] = 123
        history[0]["extension"] = {"value": "繁體 🔒", "values": [1.0, -0.0, None]}
        original = canonical_json(history)
        for encode, decode in (
            (encode_storage_history_v2, decode_storage_history_v2),
            (encode_transport_history, decode_transport_history),
        ):
            self.assertEqual(original, canonical_json(decode(encode(history))))
        self.assertEqual(original, canonical_json(snapshot_registry_history(history)))
        self.assert_code("malformed_request", self.verify, snapshot_registry_history(history))

    def test_bad_signature_and_wrong_root_never_become_authority_after_decode(self):
        for original, decode in (
            (self.storage, decode_storage_history_v2),
            (self.transport, decode_transport_history),
        ):
            value = copy.deepcopy(original)
            raw = b64url_decode(value["certificates"][0]["signature"])
            value["certificates"][0]["signature"] = b64url_encode(bytes([raw[0] ^ 1]) + raw[1:])
            self.assert_code("invalid_signature", self.verify, decode(value))
        other = AuthorityFixture()
        self.assert_code(
            "invalid_signature",
            self.verify,
            decode_storage_history_v2(self.storage),
            root_jwk=other.root_public,
            pinned_root_key_id=other.root_id,
        )

    def test_last_revocation_clock_expiry_and_rollback_results_are_unchanged(self):
        for history in (
            self.history,
            decode_storage_history_v2(self.storage),
            decode_transport_history(self.transport),
            snapshot_registry_history(self.history),
        ):
            registry = self.verify(history)
            self.assert_code(
                "key_authorization_required",
                registry.cert,
                self.f.kid("synthetic_1_agent_sig"),
                now=1000,
            )
            self.assert_code(
                "key_authorization_required",
                registry.cert,
                self.f.kid("device_sig"),
                now=5001,
            )
            self.assert_code("registry_conflict", self.verify, history, now=499)
            self.assert_code("rollback_detected", self.f.verify, history[0], previous=registry)

    def test_many_distinct_complete_resignatures_still_hit_physical_cap(self):
        previous, history = None, []
        # Same 63 certificate payloads, but genuine new ECDSA signatures on each
        # generation. These are 2016 complete JWS values, not 63 reusable values.
        for _ in range(32):
            bundle = self.f.make_bundle(previous=previous)
            previous = self.f.verify(bundle, previous=previous)
            history.append(bundle)
        keys = {
            tuple(entry["certificate"][key] for key in ("protected", "payload", "signature"))
            for bundle in history
            for entry in bundle["entries"]
        }
        self.assertEqual(2016, len(keys))
        self.assertGreater(len(canonical_json(history)), MAX_STORED_DOCUMENT_BYTES)
        self.assertLess(len(canonical_json(history)), MAX_EXPANDED_HISTORY_BYTES)
        snapshot = snapshot_registry_history(history)
        self.assertEqual(previous, self.verify(snapshot))
        for encode in (encode_storage_history_v2, encode_transport_history):
            self.assert_code("payload_too_large", encode, history)
        # A local snapshot does not change generic JSON, physical or HTTP limits.
        self.assertEqual(1048576, MAX_READ_BYTES)
        self.assertEqual(786432, MAX_STORED_DOCUMENT_BYTES)


if __name__ == "__main__":
    unittest.main()
