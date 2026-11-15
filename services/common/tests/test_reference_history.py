"""Offline storage-reference regressions; all signing keys are synthetic."""

import copy
import unittest
from unittest.mock import patch

from test_encrypted_authority import AuthorityFixture

from folioview_shared.encrypted.authority import RegistryCertificateMemo
from folioview_shared.encrypted.constants import (
    MAX_READ_BYTES,
    MAX_REGISTRY_BYTES,
    MAX_STORED_DOCUMENT_BYTES,
)
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import b64url_decode, b64url_encode, canonical_json
from folioview_shared.encrypted.reference_history import (
    REFERENCE_HISTORY_FORMAT,
    decode_reference_history,
    encode_reference_history,
)


class ReferenceHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        f = AuthorityFixture()
        f.certificates = {name: value for name, value in f.certificates.items() if "A" not in name}
        history, known, previous = [], {}, None
        memo = RegistryCertificateMemo()
        for generation in range(24):
            if generation:
                principal = f"synthetic_{generation}"
                for role in ("agent_sig", "agent_enc"):
                    f.add_key(f"{principal}_{role}", role, principal, f"connection_{generation}")
            bundle = f.make_bundle(previous=previous)
            for entry in bundle["entries"]:
                signed = entry["certificate"]
                known.setdefault(signed["payload"], signed)
                entry["certificate"] = copy.deepcopy(known[signed["payload"]])
            previous = f.verify(bundle, previous=previous, signature_memo=memo)
            history.append(bundle)
        cls.f, cls.history = f, history

    def setUp(self):
        self.small = copy.deepcopy(self.history[:2])
        self.compact = encode_reference_history(self.small)

    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(ContractError) as raised:
            function(*args, **kwargs)
        self.assertEqual(code, raised.exception.code)

    def verify(self, history, **kwargs):
        previous, memo = None, RegistryCertificateMemo()
        for bundle in history:
            previous = self.f.verify(bundle, previous=previous, signature_memo=memo, **kwargs)
        return previous

    def test_23_to_24_generations_preserve_every_signed_byte_and_order(self):
        for length, references, unique in ((23, 575, 47), (24, 624, 49)):
            with self.subTest(length=length):
                original = self.history[:length]
                compact = encode_reference_history(original)
                self.assertEqual(REFERENCE_HISTORY_FORMAT, compact["format"])
                self.assertEqual(unique, len(compact["certificates"]))
                self.assertEqual(references, sum(len(b["entries"]) for b in compact["bundles"]))
                decoded = decode_reference_history(canonical_json(compact))
                self.assertEqual(canonical_json(original), canonical_json(decoded))
                self.assertLess(len(canonical_json(compact)), MAX_STORED_DOCUMENT_BYTES)
                self.assertGreater(len(canonical_json(original)), len(canonical_json(compact)) * 4)
                self.assertEqual(self.verify(original), self.verify(decoded))

    def test_legacy_lists_and_canonical_bytes_remain_independent_lists(self):
        for value in (self.small, canonical_json(self.small)):
            with self.subTest(kind=type(value).__name__):
                result = decode_reference_history(value)
                self.assertIs(type(result), list)
                self.assertEqual(canonical_json(self.small), canonical_json(result))
                self.assertIsNot(result, self.small)
        self.assertEqual(self.small, decode_reference_history(decode_reference_history(self.small)))

    def test_near_limit_legacy_read_does_not_require_larger_reference_reencoding(self):
        # Seven one-entry templates can add a few reference-wrapper bytes rather
        # than save space. Metadata is preserved by the codec, not authenticated.
        history = [
            {
                **copy.deepcopy(self.small[0]),
                "entries": [
                    {
                        "certificate": self.f.sign(self.f.certificates["device_sig"], "root"),
                        "active": True,
                    }
                ],
                "metadata": "",
            }
            for _ in range(7)
        ]
        remaining = MAX_STORED_DOCUMENT_BYTES - 1 - len(canonical_json(history))
        for index, bundle in enumerate(history):
            bundle["metadata"] = "a" * (remaining // 7 + (index < remaining % 7))
            self.assertLessEqual(len(canonical_json(bundle)), MAX_REGISTRY_BYTES)
        raw = canonical_json(history)
        self.assertEqual(MAX_STORED_DOCUMENT_BYTES - 1, len(raw))
        self.assert_code("payload_too_large", encode_reference_history, history)
        for value in (history, raw):
            result = decode_reference_history(value)
            self.assertEqual(raw, canonical_json(result))
            # Frozen RegistryBundle rejects extra metadata both before and after;
            # the codec never upgrades a stored shape into trusted authority.
            self.assert_code("malformed_request", self.verify, result)
        self.assert_code("malformed_request", self.verify, history)

    def test_metadata_and_active_flags_are_not_discarded_or_interpreted(self):
        original = copy.deepcopy(self.small)
        original[0]["written_at"] = 123
        original[0]["extension"] = {"text": "繁體中文 🔒", "order": [3, 1, None]}
        original[1]["entries"][0]["active"] = False
        result = decode_reference_history(encode_reference_history(original))
        self.assertEqual(canonical_json(original), canonical_json(result))
        self.assertEqual(123, result[0]["written_at"])
        # The codec's structural pass cannot replace the frozen authority schema.
        self.assert_code("malformed_request", self.verify, result)

    def test_full_jws_not_payload_or_key_id_defines_deduplication(self):
        signed = self.small[0]["entries"][0]["certificate"]
        payload = self.f.certificates["device_sig"]
        resigned = self.f.sign(payload, "root")
        self.assertEqual(signed["payload"], resigned["payload"])
        self.assertNotEqual(signed["signature"], resigned["signature"])
        self.small[1]["entries"][0]["certificate"] = resigned
        compact = encode_reference_history(self.small)
        self.assertEqual(6, len(compact["certificates"]))  # Five unique certs, one new signature.
        self.assertEqual(
            canonical_json(self.small), canonical_json(decode_reference_history(compact))
        )

    def test_every_return_and_reference_owns_independent_copies(self):
        result = decode_reference_history(self.compact)
        unchanged = canonical_json(result)
        self.small[0]["checkpoint"]["signature"] = "changed"
        self.compact["certificates"][0]["signature"] = "changed"
        self.assertEqual(unchanged, canonical_json(result))
        first, second = result[0]["entries"][0], result[1]["entries"][0]
        first["certificate"]["signature"] = "changed"
        self.assertNotEqual(first["certificate"], second["certificate"])
        other = decode_reference_history(encode_reference_history(self.history[:2]))
        self.assertEqual(unchanged, canonical_json(other))

    def test_closed_format_table_and_reference_corruption_fail_closed(self):
        mutations = {
            "unknown version": lambda x: x.__setitem__("format", "other"),
            "extra wrapper": lambda x: x.__setitem__("other", 1),
            "missing wrapper": lambda x: x.pop("format"),
            "empty table": lambda x: x.__setitem__("certificates", []),
            "duplicate certificate": lambda x: x["certificates"].append(x["certificates"][0]),
            "unused certificate": lambda x: x["certificates"].append(
                x["certificates"][0] | {"signature": "A" * 86}
            ),
            "extra signed field": lambda x: x["certificates"][0].__setitem__("other", 1),
            "bad signed string": lambda x: x["certificates"][0].__setitem__("payload", "a="),
            "bool ref": lambda x: x["bundles"][0]["entries"][0].__setitem__(0, True),
            "negative ref": lambda x: x["bundles"][0]["entries"][0].__setitem__(0, -1),
            "float ref": lambda x: x["bundles"][0]["entries"][0].__setitem__(0, 0.5),
            "integral float ref": lambda x: x["bundles"][0]["entries"][0].__setitem__(0, 0.0),
            "out of range": lambda x: x["bundles"][0]["entries"][0].__setitem__(0, 999),
            "first use order": lambda x: x["bundles"][0]["entries"][0].__setitem__(0, 1),
            "bad active": lambda x: x["bundles"][0]["entries"][0].__setitem__(1, 1),
            "extra pair": lambda x: x["bundles"][0]["entries"][0].append(None),
            "extra bundle wrapper": lambda x: x["bundles"][0].__setitem__("other", 1),
            "template entries": lambda x: x["bundles"][0]["bundle"].__setitem__("entries", []),
            "missing checkpoint": lambda x: x["bundles"][0]["bundle"].pop("checkpoint"),
            "unknown contract": lambda x: x["bundles"][0]["bundle"].__setitem__(
                "contractVersion", "other"
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                value = copy.deepcopy(self.compact)
                mutate(value)
                self.assert_code("malformed_request", decode_reference_history, value)

    def test_history_entry_and_table_cardinalities_are_bounded(self):
        for function in (encode_reference_history, decode_reference_history):
            for value in ([], [self.small[0]] * 33, [{**self.small[0], "entries": []}]):
                self.assert_code("malformed_request", function, value)
        for mutate in (
            lambda x: x.__setitem__("bundles", []),
            lambda x: x.__setitem__("bundles", [x["bundles"][0]] * 33),
            lambda x: x.__setitem__(
                "certificates", [{"protected": "a", "payload": "a", "signature": "a" * 86}] * 2049
            ),
            lambda x: x["bundles"][0].__setitem__("entries", [[0, True]] * 65),
        ):
            value = copy.deepcopy(self.compact)
            mutate(value)
            self.assert_code("malformed_request", decode_reference_history, value)

    def test_exact_expanded_utf8_budget_and_consumer_tightening(self):
        size = len(canonical_json(self.small))
        self.assertEqual(
            self.small, decode_reference_history(self.compact, max_expanded_bytes=size)
        )
        self.assertEqual(
            self.compact, encode_reference_history(self.small, max_expanded_bytes=size)
        )
        for function, value in (
            (encode_reference_history, self.small),
            (decode_reference_history, self.small),
            (decode_reference_history, self.compact),
        ):
            self.assert_code("payload_too_large", function, value, max_expanded_bytes=size - 1)
            for budget in (True, False, 0, -1, 1.5, MAX_READ_BYTES + 1):
                self.assert_code("malformed_request", function, value, max_expanded_bytes=budget)

    def test_numeric_metadata_roundtrips_at_exact_canonical_budget(self):
        original = copy.deepcopy(self.small)
        original[0]["numeric"] = [1.0, -0.0, 0.0000001]
        size = len(canonical_json(original))
        compact = encode_reference_history(original, max_expanded_bytes=size)
        decoded = decode_reference_history(compact, max_expanded_bytes=size)
        self.assertEqual(canonical_json(original), canonical_json(decoded))

    def test_expansion_bomb_rejected_before_certificate_copies(self):
        compact = {
            "format": REFERENCE_HISTORY_FORMAT,
            "certificates": [self.compact["certificates"][0] | {"payload": "a" * 1500}],
            "bundles": [
                {"bundle": self.compact["bundles"][0]["bundle"], "entries": [[0, True]] * 64}
            ]
            * 32,
        }
        self.assertLess(len(canonical_json(compact)), MAX_STORED_DOCUMENT_BYTES)
        with patch("folioview_shared.encrypted.reference_history.copy.deepcopy") as clone:
            self.assert_code("payload_too_large", decode_reference_history, compact)
        clone.assert_not_called()

    def test_encoded_and_per_bundle_size_limits_are_unchanged(self):
        oversized = copy.deepcopy(self.compact)
        oversized["other"] = "a" * MAX_STORED_DOCUMENT_BYTES
        self.assert_code("payload_too_large", decode_reference_history, oversized)
        oversized = copy.deepcopy(self.small[:1])
        oversized[0]["metadata"] = "a" * MAX_REGISTRY_BYTES
        self.assert_code("payload_too_large", encode_reference_history, oversized)
        self.assert_code("payload_too_large", decode_reference_history, oversized)

    def test_stored_bytes_must_be_strict_canonical_json(self):
        raw = canonical_json(self.compact)
        for value in (
            b" " + raw,
            b"\xef\xbb\xbf" + raw,
            raw[:-1] + b',"format":"other"}',
            b"NaN",
            b"{}" * (MAX_STORED_DOCUMENT_BYTES // 2 + 1),
            raw.decode(),
            bytearray(raw),
            None,
        ):
            with self.subTest(kind=type(value).__name__):
                with self.assertRaises(ContractError):
                    decode_reference_history(value)

    def test_decoding_does_not_authenticate_pollution_wrong_root_or_current_time(self):
        compact = copy.deepcopy(self.compact)
        raw = b64url_decode(compact["certificates"][0]["signature"])
        compact["certificates"][0]["signature"] = b64url_encode(bytes([raw[0] ^ 1]) + raw[1:])
        decoded = decode_reference_history(compact)
        self.assert_code("invalid_signature", self.verify, decoded)
        decoded = decode_reference_history(self.compact)
        other = AuthorityFixture()
        self.assert_code(
            "invalid_signature",
            self.verify,
            decoded,
            root_jwk=other.root_public,
            pinned_root_key_id=other.root_id,
        )
        self.assert_code("registry_conflict", self.verify, decoded, now=499)

    def test_revocation_and_history_checks_have_identical_results(self):
        f = AuthorityFixture()
        second = f.make_bundle(previous=f.registry, revoked=("A1_sig",), key_epoch=2)
        history = [f.bundle, second]
        decoded = decode_reference_history(encode_reference_history(history))
        for candidate in (history, decoded):
            first = f.verify(candidate[0])
            last = f.verify(candidate[1], previous=first)
            self.assert_code("key_authorization_required", last.cert, f.kid("A1_sig"), now=1000)
            self.assert_code("key_authorization_required", last.cert, f.kid("device_sig"), now=5001)
            self.assert_code("rollback_detected", f.verify, candidate[0], previous=last)
            self.assert_code(
                "rollback_detected",
                f.verify,
                f.make_bundle(previous=last, key_epoch=2),
                previous=last,
            )

    def test_encoder_rejects_oversized_history_without_discarding_generations(self):
        history = [{**self.small[0], "entries": [self.small[0]["entries"][0]] * 64}] * 32
        self.assertGreater(len(canonical_json(history)), MAX_READ_BYTES)
        before = canonical_json(history)
        self.assert_code("payload_too_large", encode_reference_history, history)
        self.assertEqual(before, canonical_json(history))


if __name__ == "__main__":
    unittest.main()
