"""Validate invitation settings passed through reviewed deployment projections."""

import unittest

import test_deployment_profile as profiles
from test_browser_origin_configuration import with_aliases
from test_portfolio_hub_trust_configuration import selected

profile = profiles.profile


class InvitationDeploymentProjectionTests(unittest.TestCase):
    def test_web_modes_use_existing_owner_connection(self):
        configured = with_aliases()
        configured["webOwnerApis"]["userRecovery"] = True
        artifacts = profile.compile_web_owner_deployment_artifacts(configured)
        instance = artifacts["deployment-config.candidate.json"]
        pin = profile.digest(instance)

        for mode in ("management", "required"):
            with self.subTest(mode=mode):
                candidate = profile.add_web_invitations(instance, mode, expected_sha256=pin)
                self.assertEqual(
                    profile.terraform_inputs(candidate),
                    {**profile.terraform_inputs(instance), "workspace_invitation_mode": mode},
                )
                self.assertEqual(candidate["webOwner"], instance["webOwner"])
        with self.assertRaises(profile.ProfileError):
            profile.add_web_invitations(instance, "implicit", expected_sha256=pin)
        with self.assertRaises(profile.ProfileError):
            profile.add_web_invitations(instance, "required", expected_sha256="0" * 64)

        bare = profile.compile_target(configured, "web")
        with self.assertRaises(profile.ProfileError):
            profile.add_web_invitations(bare, "management", expected_sha256=profile.digest(bare))

    def test_admission_projection_is_limited_to_direct_user_services(self):
        configured = selected()
        for target in ("config", "portfolio", "agent-hub"):
            with self.subTest(target=target):
                instance = profile.compile_target(configured, target)
                candidate = profile.require_workspace_admission(
                    instance, expected_sha256=profile.digest(instance)
                )
                self.assertEqual(
                    profile.terraform_inputs(candidate),
                    {**profile.terraform_inputs(instance), "require_workspace_admission": True},
                )
                with self.assertRaises(profile.ProfileError):
                    profile.validate_target({**candidate, "requireWorkspaceAdmission": 1})

        for target in ("web", "user", "market", "repo"):
            with self.subTest(target=target), self.assertRaises(profile.ProfileError):
                instance = profile.compile_target(configured, target)
                profile.require_workspace_admission(
                    instance, expected_sha256=profile.digest(instance)
                )
