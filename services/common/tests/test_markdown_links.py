"""Compare bounded plaintext parsing with its original Python regex semantics."""

import copy
import html
import itertools
import random
import re
import unittest

from test_encrypted_envelope import EnvelopeFixture
from test_encrypted_schema import context_for, wrapper

from folioview_shared.encrypted.constants import CONTRACT_VERSION, PRIVATE_BYTE_LIMITS
from folioview_shared.encrypted.crypto import decrypt_jwe, encrypt_jwe, sign_jws
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json
from folioview_shared.encrypted.markdown_links import markdown_destinations
from folioview_shared.encrypted.private import _markdown, validate_private_payload
from folioview_shared.encrypted.schema import safe_https_url


def original_destinations(text):
    return (
        re.findall(r"\]\(\s*(<[^>]+>|[^\s)]+)", text)
        + re.findall(r"(?m)^\s*\[[^\]]+\]:\s*(\S+)", text)
        + re.findall(r"<([^<>\s]+:[^<>\s]*)>", text)
    )


def original_accepts(text):
    text = html.unescape(text)
    return (
        re.search(r"<\s*(?:/?[A-Za-z][A-Za-z0-9-]*(?:\s|/?>)|!|\?)", text) is None
        and re.search(r"!\s*\[", text) is None
        and all(safe_https_url(url.strip("<>")) for url in original_destinations(text))
    )


class MarkdownDestinationTests(unittest.TestCase):
    def test_exhaustive_short_capture_order_and_duplicates_match_old_regexes(self):
        alphabet = "](<:a\n["
        for size in range(6):
            for chars in itertools.product(alphabet, repeat=size):
                text = "".join(chars)
                self.assertEqual(
                    markdown_destinations(text), original_destinations(text), repr(text)
                )

    def test_unicode_reference_anchors_and_angle_fallback_preserve_python_behavior(self):
        whitespace = [chr(i) for i in range(0x110000) if chr(i).isspace()]
        self.assertEqual(
            whitespace, [chr(i) for i in range(0x110000) if re.fullmatch(r"\s", chr(i))]
        )
        for char in [*whitespace, "\ufeff", "\ud800", "\udfff", "😀", "合"]:
            for text in (
                f"]({char}<a b>) ](<>) ](<unterminated",
                f"x{char}[a]: https://example.com/a\n[b]: https://example.com/b",
                f"\n{char}\n[a\nb]:{char}https://example.com/a",
                f"<a:{char}b> <a:b:c> <:a> <a:> <<a:b>>",
            ):
                self.assertEqual(
                    markdown_destinations(text), original_destinations(text), repr(text)
                )
        self.assertEqual(markdown_destinations("x\r[a]: https://example.com"), [])
        self.assertEqual(
            markdown_destinations("x\n[a]: https://example.com"), ["https://example.com"]
        )

    def test_generated_captures_and_original_content_policy_match(self):
        rng = random.Random(20261115)
        atoms = [
            "](",
            "<",
            ">",
            ")",
            "[",
            "]:",
            "\n",
            "\r",
            "\x1c",
            "\u2028",
            " ",
            "a",
            ":",
            "https://example.com/a",
            "javascript:bad",
            "&lt;",
            "&copy;",
            "!",
            "?",
        ]
        for _ in range(3000):
            text = "".join(rng.choices(atoms, k=rng.randrange(80)))
            self.assertEqual(markdown_destinations(text), original_destinations(text), repr(text))
            try:
                _markdown(text)
                accepted = True
            except ContractError:
                accepted = False
            self.assertEqual(accepted, original_accepts(text), repr(text))

    def test_maximum_section_malformed_reference_preserves_capture_without_timing_gate(self):
        for text in ["\n" * 16384, "[" * 16384, "<" + "a:" * 8191 + "a", "](" * 8192]:
            self.assertEqual(markdown_destinations(text), original_destinations(text))

    def test_real_private_payload_byte_limit_and_signed_encrypted_round_trip(self):
        fixture = EnvelopeFixture()
        context = fixture.context()
        value = wrapper(context)
        value["payload"]["sections"] = [
            {"sectionId": "s0", "markdown": "\n" * 16384},
            {"sectionId": "s1", "markdown": "a" * 16384},
            {"sectionId": "s2", "markdown": ""},
        ]
        remaining = PRIVATE_BYTE_LIMITS["result_revision"] - len(canonical_json(value))
        self.assertTrue(0 < remaining < 16384)
        value["payload"]["sections"][2]["markdown"] = "a" * remaining
        self.assertEqual(len(canonical_json(value)), 65536)
        self.assertEqual(validate_private_payload(value, context=context), value)
        recipients = {
            row["keyId"]: next(
                cert["publicJwk"]
                for cert in fixture.certificates.values()
                if cert["keyId"] == row["keyId"]
            )
            for row in context["recipients"]
        }
        encrypted = encrypt_jwe(value, recipients, context=context)
        signed = sign_jws(
            {"context": context, "jwe": encrypted}, fixture.keys["A1_sig"], typ="fv-object+jws"
        )
        verified = fixture.verify_carrier(
            {"contractVersion": CONTRACT_VERSION, "signedObject": signed},
            context,
            grant=fixture.verify_grant(),
        )
        self.assertEqual(
            decrypt_jwe(verified.jwe, fixture.keys["device_enc"], context=context), value
        )
        oversized = copy.deepcopy(value)
        oversized["payload"]["sections"][2]["markdown"] += "a"
        with self.assertRaises(ContractError):
            validate_private_payload(oversized, context=context)

    def test_original_unsafe_and_entity_policies_still_reject(self):
        context = context_for()
        for text in [
            "[x](javascript:bad)",
            "&lt;script&gt;bad&lt;/script&gt;",
            "![x](https://example.com)",
            "\n[x]: https://user:password@example.com",
            "<a:b:c>",
        ]:
            value = wrapper(context)
            value["payload"]["sections"][0]["markdown"] = text
            with self.assertRaises(ContractError):
                validate_private_payload(value, context=context)
