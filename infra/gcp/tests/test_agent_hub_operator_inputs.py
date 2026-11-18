"""Actual private Hub input parser/diff guard; no Terraform, cloud or credentials."""

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "terraform/envs/prod/agent-hub/operator_inputs.py"
SPEC = importlib.util.spec_from_file_location("hub_operator_inputs", SCRIPT)
hub = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hub)
OWNER = "a" * 64
OTHER = "b" * 64
CANARY = "private-callback-canary"


def fixture():
    return {
        "deployment": {
            "project_id": "example-project-1234",
            "region": "europe-west3",
            "artifact_repository": "example-images",
            "runtime_account_id": "example-hub-runtime",
            "creation_image": "europe-west3-docker.pkg.dev/example-project-1234/"
            "example-images/agent-hub-api@sha256:" + "f" * 64,
            "web_origin": "https://web.example.invalid",
            "hub_origin": "https://hub.example.invalid",
        },
        "sources": {
            "user_origin": "https://user.example.invalid",
            "portfolio_origin": "https://portfolio.example.invalid",
            "portfolio_caller_email": "pf@example-project-1234.iam.gserviceaccount.com",
            "trusted_portfolio_callers": {
                "112010400000000710080": "pf@example-project-1234.iam.gserviceaccount.com"
            },
        },
        "connector": {
            "oauth_enabled": True,
            "encrypted_adapter_enabled": False,
            "muse_clients": [
                {
                    "client_id": "synthetic-muse",
                    "redirect_uris": ["https://agent.example.invalid/" + CANARY],
                    "secret_sha256": None,
                }
            ],
        },
        "agent_clients": [
            {
                "provider": "chatgpt",
                "client_id": "synthetic-chatgpt",
                "redirect_uris": ["https://other-agent.example.invalid/callback"],
                "token_endpoint_auth_method": "client_secret_basic",
                "secret_sha256": "c" * 64,
            }
        ],
        "agent_owned_mode_enabled": True,
        "agent_owned_allowed_owner_subjects": [OWNER, OTHER],
        "persistent_mode_enabled": False,
    }


def raw(value):
    return json.dumps(value).encode()


def compare(before, after, **options):
    encoded = raw(before)
    return hub.compare_rollout_inputs(
        encoded, raw(after), hashlib.sha256(encoded).hexdigest(), **options
    )


class HubOperatorInputTests(unittest.TestCase):
    def test_owner_browser_admission_is_exact_and_separate_from_the_rollout_flags(self):
        baseline = fixture()
        candidate = {**baseline, "browser_origin_aliases": ["https://alpha.example.invalid"]}
        hub.validate_full_input(candidate)
        for rejected in (
            ["https://*.example.invalid"],
            ["https://hub.example.invalid"],
            ["https://user.example.invalid"],
            ["https://alpha.example.invalid", "https://alpha.example.invalid"],
        ):
            with (
                self.subTest(rejected=rejected),
                self.assertRaisesRegex(hub.InputError, "invalid_browser_origins"),
            ):
                hub.validate_full_input({**candidate, "browser_origin_aliases": rejected})
        before = json.dumps(baseline).encode()
        after = json.dumps(candidate).encode()
        with self.assertRaisesRegex(hub.InputError, "protected_inputs_changed"):
            hub.compare_rollout_inputs(before, after, hashlib.sha256(before).hexdigest())

    def test_complete_supported_input_changes_only_flags_and_reports_no_private_values(self):
        before = fixture()
        after = {**before, **dict.fromkeys(hub.FLAGS, True)}
        report = compare(before, after, owner_subject=OWNER)
        self.assertTrue(report["localOwnerMembership"])
        self.assertFalse(compare(before, after, owner_subject="d" * 64)["localOwnerMembership"])
        self.assertFalse(report["productionMembershipVerified"])
        self.assertFalse(report["activationAuthorized"])
        self.assertTrue(
            all(row == {"before": False, "after": True} for row in report["flags"].values())
        )
        for private in [OWNER, OTHER, CANARY, "synthetic-muse", "c" * 64, "portfolio@example"]:
            self.assertNotIn(private, json.dumps(report))

    def test_defaults_remain_closed_including_when_personal_mode_is_already_true(self):
        for value in [fixture(), {"deployment": fixture()["deployment"]}]:
            report = compare(value, value)
            self.assertTrue(
                all(row == {"before": False, "after": False} for row in report["flags"].values())
            )

    def test_digest_binds_original_bytes_not_reencoded_equivalent_object(self):
        baseline = raw(fixture())
        reordered = json.dumps(fixture(), sort_keys=True, indent=2).encode()
        self.assertNotEqual(baseline, reordered)
        self.assertEqual(json.loads(baseline), json.loads(reordered))
        with self.assertRaises(hub.InputError):
            hub.compare_rollout_inputs(reordered, baseline, hashlib.sha256(baseline).hexdigest())
        self.assertTrue(
            hub.compare_rollout_inputs(reordered, baseline, hashlib.sha256(reordered).hexdigest())[
                "protectedInputsUnchanged"
            ]
        )
        for bad in [{}, bytearray(baseline), "private"]:
            with self.assertRaises(hub.InputError):
                hub.compare_rollout_inputs(bad, baseline, hashlib.sha256(baseline).hexdigest())

    def test_both_inputs_are_validated_before_comparison(self):
        valid = fixture()
        invalid = {**valid, "unexpected": CANARY}
        for before, after in [(invalid, valid), (valid, invalid)]:
            with self.assertRaises(hub.InputError):
                compare(before, after)

    def test_unknown_nested_fields_never_silently_disappear(self):
        paths = [
            (),
            ("deployment",),
            ("sources",),
            ("connector",),
            ("connector", "muse_clients", 0),
            ("agent_clients", 0),
        ]
        for path in paths:
            value = fixture()
            selected = value
            for step in path:
                selected = selected[step]
            selected["raw-client-secret-canary"] = CANARY
            with self.assertRaises(hub.InputError) as caught:
                compare(value, value)
            self.assertNotIn(CANARY, str(caught.exception))
            self.assertNotIn("raw-client-secret", str(caught.exception))

    def test_duplicate_nonfinite_malformed_and_nonobject_json_reject(self):
        for value in [
            b'{"deployment":{},"deployment":{}}',
            b'{"deployment":{"region":"one","region":"two"}}',
            b'{"deployment":NaN}',
            b'{"deployment":Infinity}',
            b"[]",
            b"null",
            b"{",
            b"\xff",
        ]:
            with self.assertRaises(hub.InputError):
                hub.decode_input(value)

    def test_bool_fields_never_coerce_null_integer_or_text(self):
        for name in [*hub.FLAGS, "agent_owned_mode_enabled", "persistent_mode_enabled"]:
            for invalid in [None, 0, 1, "false", [], {}]:
                value = fixture()
                value[name] = invalid
                with self.assertRaises(hub.InputError):
                    compare(value, value)
        for name in ["oauth_enabled", "encrypted_adapter_enabled"]:
            value = fixture()
            value["connector"][name] = None
            with self.assertRaises(hub.InputError):
                compare(value, value)

    def test_all_slot_task_mode_dependency_combinations(self):
        for mode in [False, True]:
            for slots in [False, True]:
                for tasks in [False, True]:
                    value = fixture()
                    value.update(
                        agent_owned_mode_enabled=mode,
                        provider_connection_slots_enabled=slots,
                        task_center_enabled=tasks,
                    )
                    allowed = (not slots or mode) and (not tasks or (slots and mode))
                    if allowed:
                        compare(value, value)
                    else:
                        with self.assertRaises(hub.InputError):
                            compare(value, value)

    def test_protected_values_list_order_and_owner_widening_remain_exact(self):
        before = fixture()
        cases = []
        for key, changed in [
            ("agent_owned_mode_enabled", False),
            ("agent_owned_allowed_owner_subjects", [OTHER, OWNER]),
            ("agent_owned_allowed_owner_subjects", [OWNER, OTHER, "d" * 64]),
        ]:
            value = copy.deepcopy(before)
            value[key] = changed
            cases.append(value)
        for path in [
            ("deployment", "web_origin"),
            ("deployment", "creation_image"),
            ("sources", "portfolio_origin"),
            ("agent_clients", 0, "secret_sha256"),
        ]:
            value = copy.deepcopy(before)
            selected = value
            for step in path[:-1]:
                selected = selected[step]
            selected[path[-1]] = (
                "e" * 64 if path[-1] == "secret_sha256" else "https://different.example.invalid"
            )
            cases.append(value)
        for after in cases:
            with self.assertRaises(hub.InputError):
                compare(before, after)

    def test_owner_and_client_bounds_and_prerequisites_remain_enforced(self):
        for owners in [
            None,
            [OWNER, OWNER],
            ["not-a-subject"],
            ["a" * 63],
            [hashlib.sha256(str(i).encode()).hexdigest() for i in range(33)],
        ]:
            value = fixture()
            value["agent_owned_allowed_owner_subjects"] = owners
            with self.assertRaises(hub.InputError):
                compare(value, value)
        for key, item in [
            ("sources", {}),
            ("connector", {}),
            ("agent_owned_allowed_owner_subjects", []),
        ]:
            value = fixture()
            value[key] = item
            with self.assertRaises(hub.InputError):
                compare(value, value)
        value = fixture()
        value["agent_clients"][0]["client_id"] = "synthetic-muse"
        with self.assertRaises(hub.InputError):
            compare(value, value)

    def test_optional_legacy_forms_remain_supported_without_normalization(self):
        value = fixture()
        value["bootstrap_image"] = value["deployment"]["creation_image"]
        value["connector"]["muse_clients"][0]["token_endpoint_auth_method"] = None
        self.assertTrue(compare(value, value)["protectedInputsUnchanged"])
        value = {
            "deployment": fixture()["deployment"],
            "bootstrap_image": None,
            "sources": {"user_origin": None, "trusted_portfolio_callers": None},
            "connector": {"muse_clients": None},
        }
        self.assertTrue(compare(value, value)["protectedInputsUnchanged"])
        for key, bad in [("muse_clients", {}), ("muse_clients", False)]:
            value = fixture()
            value["connector"][key] = bad
            with self.assertRaises(hub.InputError):
                compare(value, value)
        value = fixture()
        value["agent_clients"][0]["token_endpoint_auth_method"] = False
        with self.assertRaises(hub.InputError):
            compare(value, value)
        value = fixture()
        value["sources"]["trusted_portfolio_callers"] = []
        with self.assertRaises(hub.InputError):
            compare(value, value)

    def test_actual_cli_emits_only_redacted_result_or_fixed_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            before = raw(fixture())
            after = raw({**fixture(), **dict.fromkeys(hub.FLAGS, True)})
            baseline, candidate = folder / "baseline.json", folder / "candidate.json"
            baseline.write_bytes(before)
            candidate.write_bytes(after)
            command = [
                sys.executable,
                str(SCRIPT),
                "--baseline",
                str(baseline),
                "--candidate",
                str(candidate),
                "--expected-baseline-sha256",
                hashlib.sha256(before).hexdigest(),
            ]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertTrue(json.loads(result.stdout)["protectedInputsUnchanged"])
            self.assertNotIn(CANARY, result.stdout + result.stderr)
            candidate.write_bytes(b'{"secret":"private-callback-canary"}')
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout), {"error": "unexpected_fields"})
            self.assertNotIn(CANARY, result.stdout + result.stderr)
