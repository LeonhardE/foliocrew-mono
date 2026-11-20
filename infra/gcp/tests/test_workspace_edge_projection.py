"""Check the closed Workbench edge projection without changing existing targets."""

import json
import tempfile
import unittest
from pathlib import Path

import test_deployment_profile as profiles
import test_terraform_pipeline as pipelines
from test_portfolio_hub_trust_configuration import selected

profile = profiles.profile
runner = pipelines.pipeline
EDGE = {
    "browserOrigin": "https://hub.example.test",
    "publicKey": "m-cQA9lh6oJmA1Kn74lPpBu0TjkXtYoCBXco7JRq6EI",
}


class WorkspaceEdgeTests(unittest.TestCase):
    def test_pins_exact_web_deployment_and_preserves_owner_and_build(self):
        artifacts = profile.compile_web_owner_deployment_artifacts(selected())
        pin = artifacts["trigger-substitutions.candidate.json"]
        instance = profile.parse_target(pin["_DEPLOYMENT_CONFIG"].encode())
        extended = profile.add_workspace_edge(
            instance, EDGE, expected_sha256=pin["_DEPLOYMENT_SHA256"]
        )
        self.assertEqual({k: v for k, v in extended.items() if k != "workspaceEdge"}, instance)
        self.assertEqual(
            profile.terraform_inputs(extended),
            {
                **profile.terraform_inputs(instance),
                "workspace_edge": {
                    "browser_origin": EDGE["browserOrigin"],
                    "public_key": EDGE["publicKey"],
                },
            },
        )
        with self.assertRaises(profile.ProfileError):
            profile.add_workspace_edge(instance, EDGE, expected_sha256="0" * 64)
        self.assertNotIn("workspace_edge", profile.terraform_inputs(instance))

    def test_requires_valid_dns_origin_and_canonical_encoded_key(self):
        instance = profile.compile_target(selected(), "web")
        reserved = (
            f"https://market-web-{instance['project']['number']}.{instance['region']}.run.app"
        )
        for override in (
            {"browserOrigin": "https://hub.example.test/"},
            {"browserOrigin": "https://hub.example.test:443"},
            {"browserOrigin": "http://hub.example.test"},
            {"browserOrigin": "https://hub..example.test"},
            {"browserOrigin": reserved},
            {"publicKey": EDGE["publicKey"][:-1] + "J"},
            {"privateKey": "unexpected"},
        ):
            with self.subTest(field=next(iter(override))), self.assertRaises(profile.ProfileError):
                profile.add_workspace_edge(
                    instance, {**EDGE, **override}, expected_sha256=profile.digest(instance)
                )
        for target in ("market", "user", "config", "portfolio", "agent-hub", "repo"):
            instance = profile.compile_target(selected(), target)
            with self.subTest(target=target), self.assertRaises(profile.ProfileError):
                profile.add_workspace_edge(instance, EDGE, expected_sha256=profile.digest(instance))

    def test_consumer_requires_exact_marker(self):
        marker = {
            "schemaVersion": 1,
            "target": "web",
            "configurationContract": "workspace-edge.v1",
            "terraformVariable": "workspace_edge",
        }
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            path = directory / "workspace-edge.consumer.json"
            with self.assertRaisesRegex(RuntimeError, "Workbench edge contract"):
                runner.require_workspace_edge_consumer(directory)
            path.write_text(json.dumps({**marker, "target": "market"}))
            with self.assertRaisesRegex(RuntimeError, "Workbench edge contract"):
                runner.require_workspace_edge_consumer(directory)
            path.write_text(json.dumps(marker))
            runner.require_workspace_edge_consumer(directory)
            with self.assertRaisesRegex(RuntimeError, "Agent link stages"):
                runner.require_workspace_edge_consumer(directory, agent_links=True)
            (directory / "workspace-edge-agent-links.consumer.json").write_text(
                json.dumps({**marker, "configurationContract": "workspace-edge-agent-links.v1"})
            )
            runner.require_workspace_edge_consumer(directory, agent_links=True)

    def test_agent_link_modes_require_the_fixed_workbench_and_active_owner_hub(self):
        artifacts = profile.compile_web_owner_deployment_artifacts(selected())
        pin = artifacts["trigger-substitutions.candidate.json"]
        instance = profile.parse_target(pin["_DEPLOYMENT_CONFIG"].encode())
        branded = {**EDGE, "browserOrigin": "https://hub.foliocrew.app"}
        for mode in ("admitted", "preferred"):
            edge = {**branded, "agentLinkMode": mode}
            extended = profile.add_workspace_edge(
                instance, edge, expected_sha256=profile.digest(instance)
            )
            self.assertEqual(
                profile.terraform_inputs(extended)["workspace_edge"]["agent_link_mode"], mode
            )
            self.assertEqual(extended["webOwner"], instance["webOwner"])
        without_owner = profile.compile_target(selected(), "web")
        for base, edge in (
            (instance, {**EDGE, "agentLinkMode": "admitted"}),
            (instance, {**branded, "agentLinkMode": "implicit"}),
            (without_owner, {**branded, "agentLinkMode": "preferred"}),
        ):
            with self.subTest(edge=edge), self.assertRaises(profile.ProfileError):
                profile.add_workspace_edge(base, edge, expected_sha256=profile.digest(base))
