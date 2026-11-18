"""Offline browser-origin candidates and compatibility of active runner inputs."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_deployment_profile as profiles
from test_portfolio_hub_trust_configuration import selected

profile = profiles.profile
BRANDED = "https://hub.example.test"
SECONDARY = "https://workspace.example.test"


def with_aliases(**selections):
    return {**selected(), "schemaVersion": 6, "browserOrigins": selections}


class BrowserOriginTests(unittest.TestCase):
    def test_v6_preserves_existing_deployment_and_identity_projections(self):
        old = selected()
        new = with_aliases(market=[BRANDED], user=[BRANDED])
        for target in profile.TARGET_SERVICES:
            self.assertEqual(
                profile.compile_artifacts(new, target), profile.compile_artifacts(old, target)
            )
        for compiler in (
            profile.compile_user_hub_trust_artifacts,
            profile.compile_portfolio_hub_trust_artifacts,
            profile.compile_web_owner_deployment_artifacts,
        ):
            old_trust, new_trust = compiler(old), compiler(new)
            self.assertNotEqual(
                old_trust["manifest.json"].pop("profileSha256"),
                new_trust["manifest.json"].pop("profileSha256"),
            )
            self.assertEqual(old_trust, new_trust)
        old_render, new_render = profile.render(old), profile.render(new)
        for name, payload in old_render.items():
            if name != "manifest.json":
                self.assertEqual(new_render[name], payload)
        self.assertEqual(
            new_render["manifest.json"]["filesSha256"], old_render["manifest.json"]["filesSha256"]
        )
        for target in ("market", "user", "config", "agent-hub"):
            with self.subTest(target=target):
                with self.assertRaises(profile.ProfileError):
                    profile.compile_browser_origin_artifacts(old, target)
        with self.assertRaises(profile.ProfileError):
            profile.compile_browser_origin_artifacts(new, "config")

    def test_membership_is_sorted_and_explicit_for_each_target(self):
        for target in profile.BROWSER_ORIGIN_TARGETS:
            with self.subTest(target=target):
                selected_order = [SECONDARY, BRANDED]
                value = with_aliases(**{target: selected_order})
                candidate = profile.compile_browser_origin_artifacts(value, target)
                instance = profile.compile_target(value, target)
                document = candidate["browser-origins.candidate.json"]
                self.assertEqual(document["target"], target)
                self.assertEqual(document["additionalOrigins"], [BRANDED, SECONDARY])
                self.assertEqual(selected_order, [SECONDARY, BRANDED])
                self.assertEqual(
                    profile.parse_browser_origins(
                        profile.canonical(document),
                        instance=instance,
                        web_origin=value["targets"]["web"]["origin"],
                        expected_sha256=candidate["manifest.json"]["browserOriginsSha256"],
                    ),
                    document,
                )
                self.assertEqual(
                    candidate,
                    profile.compile_browser_origin_artifacts(
                        with_aliases(**{target: list(reversed(selected_order))}), target
                    ),
                )

    def test_unsafe_origins_and_unselected_environments_are_rejected(self):
        for addresses in (
            [],
            [BRANDED, BRANDED],
            [f"https://h{index}.example.test" for index in range(8)],
            ["http://hub.example.test"],
            ["https://HUB.example.test"],
            ["https://*.example.test"],
            ["https://x@hub.example.test"],
            ["https://hub.example.test:443"],
            ["https://hub.example.test/"],
            ["https://hub.example.test?x=1"],
            ["https://hub.example.test#x"],
            ["https://hub.example.test."],
            ["https://hub.-example.test"],
            ["https://127.0.0.1"],
            [selected()["targets"]["web"]["origin"]],
            [selected()["targets"]["agent-hub"]["origin"]],
        ):
            with self.subTest(addresses=addresses), self.assertRaises(profile.ProfileError):
                profile.validate_profile(with_aliases(market=addresses))
        for target in ("portfolio", "repo", "web", "all"):
            with self.subTest(target=target), self.assertRaises(profile.ProfileError):
                profile.validate_profile(with_aliases(**{target: [BRANDED]}))
        fresh = profiles.example()
        version_six = with_aliases(market=[BRANDED])
        version_six.update(mode=fresh["mode"], targets=fresh["targets"])
        with self.assertRaises(profile.ProfileError):
            profile.validate_profile(version_six)
        with self.assertRaises(profile.ProfileError):
            profile.validate_profile({**with_aliases(market=[BRANDED]), "schemaVersion": 5})

    def test_reader_requires_exact_target_instance_and_reviewed_hash(self):
        value = with_aliases(user=[BRANDED, SECONDARY])
        instance = profile.compile_target(value, "user")
        artifacts = profile.compile_browser_origin_artifacts(value, "user")
        document = artifacts["browser-origins.candidate.json"]
        origin = value["targets"]["web"]["origin"]
        digest = artifacts["manifest.json"]["browserOriginsSha256"]
        different = profile.compile_target({**value, "profileId": "different-instance"}, "user")
        for other_instance, other_origin, other_digest in (
            (different, origin, digest),
            (profile.compile_target(value, "market"), origin, digest),
            (instance, "https://other.example.test", digest),
            (instance, origin, "0" * 64),
        ):
            with self.assertRaises(profile.ProfileError):
                profile.parse_browser_origins(
                    profile.canonical(document),
                    instance=other_instance,
                    web_origin=other_origin,
                    expected_sha256=other_digest,
                )
        for bad in (
            {**document, "additionalOrigins": [SECONDARY, BRANDED]},
            {**document, "preferredOrigin": BRANDED},
            {**document, "additionalOrigins": [origin]},
        ):
            with self.assertRaises(profile.ProfileError):
                profile.parse_browser_origins(
                    profile.canonical(bad),
                    instance=instance,
                    web_origin=origin,
                    expected_sha256=profile.digest(bad),
                )

    def test_offline_cli_writes_only_candidate_and_manifest(self):
        directory = profiles.DIRECTORY / "deployment-profiles"
        example = directory / "example-v6.profile.json"
        schema = json.loads((directory / "profile-v6.schema.json").read_text())
        self.assertEqual(
            set(schema["properties"]["browserOrigins"]["properties"]),
            profile.BROWSER_ORIGIN_TARGETS,
        )
        value = profile.load_profile(example)
        self.assertEqual(set(value), set(schema["required"]))
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "new-candidate"
            args = [
                sys.executable,
                str(profiles.DIRECTORY / "deployment_profile.py"),
                "compile-browser-origins",
                "--profile",
                str(example),
                "--target",
                "market",
                "--output-dir",
                str(dest),
            ]
            result = subprocess.run(args, capture_output=True, text=True, check=True)
            self.assertNotIn("workspace.demo.example", result.stdout)
            self.assertEqual(
                {path.name for path in dest.iterdir()},
                {"browser-origins.candidate.json", "manifest.json"},
            )
            self.assertFalse(json.loads(result.stdout)["productionActivation"])
            retry = subprocess.run(args, capture_output=True, text=True)
            self.assertNotEqual(retry.returncode, 0)

    def test_managed_inputs_extend_the_existing_user_deployment(self):
        value = with_aliases(user=[BRANDED])
        deployment = profile.compile_user_hub_trust_artifacts(value)
        instance = deployment["deployment-config.candidate.json"]
        candidate = profile.compile_browser_origin_artifacts(value, "user")
        extended = profile.add_browser_origins(
            instance,
            profile.canonical(candidate["browser-origins.candidate.json"]),
            expected_sha256=candidate["manifest.json"]["browserOriginsSha256"],
        )
        self.assertEqual(
            profile.terraform_inputs(extended),
            {**deployment["terraform-inputs.candidate.json"], "browser_origin_aliases": [BRANDED]},
        )
        self.assertNotIn("browserOrigins", instance)
        self.assertEqual(
            {key: item for key, item in extended.items() if key != "browserOrigins"}, instance
        )
        with self.assertRaises(profile.ProfileError):
            profile.validate_target(
                {**profile.compile_target(value, "web"), "browserOrigins": [BRANDED]}
            )

    def test_managed_runner_requires_exact_consumer_opt_in(self):
        pipeline = profiles.pipeline
        value = with_aliases(market=[BRANDED])
        legacy = profile.compile_target(value, "market")
        candidate = profile.compile_browser_origin_artifacts(value, "market")
        extended = profile.add_browser_origins(
            legacy,
            profile.canonical(candidate["browser-origins.candidate.json"]),
            expected_sha256=candidate["manifest.json"]["browserOriginsSha256"],
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            relative = "infra/gcp/terraform/envs/prod/market"
            directory = root / relative
            directory.mkdir(parents=True)
            policy = {
                "schema_version": 2,
                "targets": {
                    "market": {
                        "enabled": True,
                        "directory": relative,
                        "deployment_source": "trigger-v1",
                        "configuration_controllers": ["module.market.terraform_data.configuration"],
                    },
                },
            }
            (root / pipeline.POLICY).write_text(json.dumps(policy))
            (root / "infra/gcp/terraform/toolchain.json").write_text(
                (profiles.DIRECTORY / "terraform/toolchain.json").read_text()
            )
            self.assertEqual(pipeline.registry(root, "market", legacy)[2], directory)
            with self.assertRaisesRegex(RuntimeError, "has not adopted"):
                pipeline.registry(root, "market", extended)
            marker = directory / "browser-origins.consumer.json"
            selection = {
                "schemaVersion": 1,
                "target": "market",
                "configurationContract": "browser-origins.v1",
                "terraformVariable": "browser_origin_aliases",
            }
            marker.write_text(json.dumps({**selection, "target": "user"}))
            with self.assertRaisesRegex(RuntimeError, "has not adopted"):
                pipeline.registry(root, "market", extended)
            marker.write_text(json.dumps(selection))
            self.assertEqual(pipeline.registry(root, "market", extended)[0]["deployment"], extended)
