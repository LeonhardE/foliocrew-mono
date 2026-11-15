"""Packaged schema integrity is separate from untrusted input validation."""

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from importlib.resources import files
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from folioview_shared import valuation
from folioview_shared.encrypted import schema
from folioview_shared.encrypted.errors import ContractError


class PackagedSchemaIntegrityTests(unittest.TestCase):
    def setUp(self):
        schema._document.cache_clear()
        schema._validator.cache_clear()
        self.raw = files("folioview_shared.encrypted").joinpath("schemas.json").read_bytes()

    def tearDown(self):
        schema._document.cache_clear()
        schema._validator.cache_clear()

    def test_exact_packaged_bytes_pass_the_complete_meta_schema_independently(self):
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), schema._PACKAGED_SCHEMA_SHA256)
        # This direct check is mandatory in the common suite. Do not replace it
        # with _document/load_schema: runtime intentionally does not repeat it.
        document = json.loads(self.raw.decode("utf-8"))
        Draft202012Validator.check_schema(document)
        self.assertEqual(schema.load_schema("PublicJWK")["$defs"], document["$defs"])

    def test_changed_bytes_fail_before_json_parsing_or_validator_creation(self):
        altered = json.loads(self.raw.decode("utf-8"))
        altered["$defs"]["PublicJWK"]["additionalProperties"] = True
        candidates = (
            self.raw + b" ",  # Same JSON meaning still requires the exact packaged bytes.
            json.dumps(altered).encode("utf-8"),  # Valid JSON with weakened input constraints.
            self.raw[:-3],
            b"\xff" + self.raw,
            b"",
        )
        for raw in candidates:
            schema._document.cache_clear()
            schema._validator.cache_clear()
            with (
                self.subTest(length=len(raw)),
                patch.object(schema, "files") as resources,
                patch.object(schema.json, "loads") as parse,
                patch.object(schema, "Draft202012Validator") as validator,
            ):
                resources.return_value.joinpath.return_value.read_bytes.return_value = raw
                with self.assertRaises(ContractError) as failure:
                    schema._validator("PublicJWK")
                self.assertEqual(failure.exception.code, "authorization_unavailable")
                self.assertEqual(failure.exception.status, 503)
                parse.assert_not_called()
                validator.assert_not_called()

    def test_unreadable_package_fails_with_a_fixed_diagnostic_before_validation(self):
        with (
            patch.object(schema, "files") as resources,
            patch.object(schema.json, "loads") as parse,
            patch.object(schema, "Draft202012Validator") as validator,
        ):
            resources.return_value.joinpath.return_value.read_bytes.side_effect = OSError(
                "synthetic private path"
            )
            with self.assertRaises(ContractError) as failure:
                schema._validator("PublicJWK")
            self.assertEqual(str(failure.exception), "authorization_unavailable")
            parse.assert_not_called()
            validator.assert_not_called()

    def test_verified_runtime_definition_does_not_repeat_the_meta_schema_check(self):
        public = {"kty": "EC", "crv": "P-256", "x": "A" * 43, "y": "B" * 43}
        with patch.object(Draft202012Validator, "check_schema") as meta:
            self.assertEqual(schema.validate_schema("PublicJWK", public), public)
            with self.assertRaises(ContractError):
                schema.validate_schema("PublicJWK", public | {"extra": "rejected"})
            meta.assert_not_called()

    def test_integrity_failure_does_not_cache_an_unverified_definition(self):
        with patch.object(schema, "files") as resources:
            resources.return_value.joinpath.return_value.read_bytes.return_value = self.raw + b" "
            with self.assertRaises(ContractError):
                schema.load_schema("PublicJWK")
        self.assertEqual(schema._document.cache_info().currsize, 0)
        self.assertEqual(schema.load_schema("PublicJWK")["$ref"], "#/$defs/PublicJWK")

    def test_public_schema_and_checked_input_copies_remain_detached(self):
        public = {"kty": "EC", "crv": "P-256", "x": "A" * 43, "y": "B" * 43}
        loaded = schema.load_schema("PublicJWK")
        loaded["$defs"]["PublicJWK"]["required"] = []
        loaded["$defs"]["PublicJWK"]["additionalProperties"] = True
        with self.assertRaises(ContractError):
            schema.validate_schema("PublicJWK", {"extra": "rejected"})
        original = copy.deepcopy(public)
        checked = schema.validate_schema("PublicJWK", public)
        checked["x"] = "changed"
        self.assertEqual(public, original)
        self.assertEqual(schema.validate_schema("PublicJWK", public), original)

    def test_installed_package_resource_has_the_same_pinned_bytes(self):
        # CI installs the actual wheel before the common suite. -I removes its
        # source PYTHONPATH, so this also checks the independently installed data.
        # The development environment's existing editable install is supported.
        script = """\
import hashlib, json, sys
from importlib.resources import files
from jsonschema import Draft202012Validator
raw = files('folioview_shared.encrypted').joinpath('schemas.json').read_bytes()
assert hashlib.sha256(raw).hexdigest() == sys.argv[1]
Draft202012Validator.check_schema(json.loads(raw.decode('utf-8')))
print(hashlib.sha256(raw).hexdigest())
"""
        with tempfile.TemporaryDirectory(prefix="folioview-schema-package-") as directory:
            result = subprocess.run(
                [sys.executable, "-I", "-c", script, schema._PACKAGED_SCHEMA_SHA256],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(result.returncode, 0, "Isolated packaged schema verification failed.")
        self.assertEqual(result.stdout.strip(), schema._PACKAGED_SCHEMA_SHA256)


class PackagedValuationSchemaIntegrityTests(unittest.TestCase):
    def setUp(self):
        valuation._document.cache_clear()
        valuation._validator.cache_clear()
        self.raw = files("folioview_shared").joinpath("valuation_schemas.json").read_bytes()

    def tearDown(self):
        valuation._document.cache_clear()
        valuation._validator.cache_clear()

    def test_packaged_definition_passes_full_meta_schema_and_preserves_every_public_root_ref(self):
        self.assertEqual(
            hashlib.sha256(self.raw).hexdigest(), valuation._PACKAGED_VALUATION_SCHEMA_SHA256
        )
        # Independent mandatory CI validation, not a call to the pinned loader.
        document = json.loads(self.raw.decode("utf-8"))
        Draft202012Validator.check_schema(document)
        for name in document["$defs"]:
            with self.subTest(name=name):
                self.assertEqual(
                    valuation.load_valuation_schema(name),
                    {**document, "$ref": "#/$defs/" + name},
                )
        manifest = Path(__file__).resolve().parents[3] / (
            "packages/encrypted-workspace/valuation/integrity.json"
        )
        self.assertEqual(
            json.loads(manifest.read_text())["schemaSha256"],
            valuation._PACKAGED_VALUATION_SCHEMA_SHA256,
        )

    def test_altered_schema_bytes_are_refused_before_parse_or_validator_creation(self):
        altered = json.loads(self.raw.decode("utf-8"))
        altered["$defs"]["Currency"]["enum"].append("BAD")
        for raw in (
            self.raw + b" ",
            json.dumps(altered).encode("utf-8"),
            self.raw[:-3],
            b"\xff" + self.raw,
            b"",
        ):
            valuation._document.cache_clear()
            valuation._validator.cache_clear()
            with (
                self.subTest(length=len(raw)),
                patch.object(valuation, "files") as resources,
                patch.object(valuation.json, "loads") as parse,
                patch.object(valuation, "Draft202012Validator") as validator,
            ):
                resources.return_value.joinpath.return_value.read_bytes.return_value = raw
                with self.assertRaises(valuation.ValuationError) as failure:
                    valuation._validator("Currency")
                self.assertEqual(failure.exception.code, "invalid_input")
                parse.assert_not_called()
                validator.assert_not_called()
                self.assertEqual(valuation._document.cache_info().currsize, 0)
                self.assertEqual(valuation._validator.cache_info().currsize, 0)

    def test_incorrect_pin_and_unreadable_resource_fail_with_fixed_diagnostic(self):
        with (
            patch.object(valuation, "_PACKAGED_VALUATION_SCHEMA_SHA256", "0" * 64),
            patch.object(valuation.json, "loads") as parse,
            self.assertRaises(valuation.ValuationError) as failure,
        ):
            valuation.load_valuation_schema("Currency")
        self.assertEqual(str(failure.exception), "invalid_input")
        parse.assert_not_called()
        with (
            patch.object(valuation, "files") as resources,
            patch.object(valuation.json, "loads") as parse,
        ):
            resources.return_value.joinpath.return_value.read_bytes.side_effect = OSError(
                "synthetic private resource path"
            )
            with self.assertRaises(valuation.ValuationError) as failure:
                valuation.load_valuation_schema("Currency")
            self.assertEqual(str(failure.exception), "invalid_input")
            parse.assert_not_called()
        self.assertEqual(valuation._document.cache_info().currsize, 0)
        self.assertEqual(valuation.load_valuation_schema("Currency")["$ref"], "#/$defs/Currency")

    def test_runtime_omits_only_meta_schema_work_and_keeps_input_formats_fields_and_byte_checks(
        self,
    ):
        with patch.object(Draft202012Validator, "check_schema") as meta:
            value = {"defaultPortfolioCurrency": "USD"}
            self.assertEqual(
                valuation.validate_valuation_schema("CurrencyPreferences", value), value
            )
            for name, invalid in (
                ("CurrencyPreferences", {**value, "extra": "rejected"}),
                ("Currency", "BAD"),
                ("Date", "2026-02-30"),
                ("Timestamp", "2026-11-15T11:00:00+01:00"),
                ("Timestamp", "not-a-time"),
            ):
                with (
                    self.subTest(name=name, invalid=invalid),
                    self.assertRaises(valuation.ValuationError),
                ):
                    valuation.validate_valuation_schema(name, invalid)
            with self.assertRaises(valuation.ValuationError) as failure:
                valuation.validate_valuation_schema("CurrencyPreferences", {"x": "x" * 1_048_576})
            self.assertEqual(failure.exception.code, "payload_too_large")
            meta.assert_not_called()

    def test_schema_and_input_copies_cannot_mutate_verified_runtime_constraints(self):
        loaded = valuation.load_valuation_schema("Currency")
        loaded["$defs"]["Currency"]["enum"].append("BAD")
        with self.assertRaises(valuation.ValuationError):
            valuation.validate_valuation_schema("Currency", "BAD")
        value = {"defaultPortfolioCurrency": "USD"}
        checked = valuation.validate_valuation_schema("CurrencyPreferences", value)
        checked["defaultPortfolioCurrency"] = "CAD"
        self.assertEqual(value, {"defaultPortfolioCurrency": "USD"})
        self.assertEqual(valuation.validate_valuation_schema("CurrencyPreferences", value), value)

    def test_installed_package_bytes_pass_full_meta_schema_independently_of_runtime_loader(self):
        # The common CI job installs this package. -I excludes source PYTHONPATH;
        # local development can retain its existing compatible editable install.
        script = """\
import hashlib, json, sys
from importlib.resources import files
from jsonschema import Draft202012Validator
raw = files('folioview_shared').joinpath('valuation_schemas.json').read_bytes()
assert hashlib.sha256(raw).hexdigest() == sys.argv[1]
Draft202012Validator.check_schema(json.loads(raw.decode('utf-8')))
print(hashlib.sha256(raw).hexdigest())
"""
        with tempfile.TemporaryDirectory(prefix="folioview-valuation-schema-package-") as directory:
            result = subprocess.run(
                [sys.executable, "-I", "-c", script, valuation._PACKAGED_VALUATION_SCHEMA_SHA256],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(result.returncode, 0, "Isolated packaged valuation schema check failed.")
        self.assertEqual(result.stdout.strip(), valuation._PACKAGED_VALUATION_SCHEMA_SHA256)


if __name__ == "__main__":
    unittest.main()
