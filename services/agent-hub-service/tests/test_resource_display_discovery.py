"""Compound composition uses the real bounded delegated User/Portfolio readers."""

import json
import unittest
from unittest.mock import patch

import httpx
import test_catalogue as catalogue_fixture
from fixtures import SOURCE, UID

from app.resource_display import ResourceDisplayService


class ResourceDisplayDiscoveryTests(catalogue_fixture.CatalogueFixture, unittest.TestCase):
    def read(self, uid=UID, sources=None):
        return ResourceDisplayService(self.vaults, sources or self.sources).read(uid)

    def test_exact_existing_discovery_dtos_credential_targets_and_two_network_calls(self):
        result = self.read()
        self.assertEqual(result["mode"], "full")
        self.assertEqual(result["catalogue"]["groups"][0]["items"][0]["snapshotId"], self.snapshot)
        self.assertEqual(len(self.calls), 2)
        self.assertCountEqual(
            self.token_calls, [catalogue_fixture.USER, catalogue_fixture.PORTFOLIO]
        )
        self.assertEqual(self.owners, [UID, UID])
        self.assertEqual(result["displayNames"]["items"], [])

    def test_wrong_extra_oversize_or_failed_producer_remains_truthful_not_separate_success(self):
        responses = [
            lambda: httpx.Response(
                200, json={"contractVersion": "wrong", "private": "DO_NOT_REFLECT"}
            ),
            lambda: httpx.Response(
                200, content=b" " * 1_048_577, headers={"Content-Type": "application/json"}
            ),
            lambda: httpx.Response(401, json={"private": "DO_NOT_REFLECT"}),
            lambda: httpx.Response(503, json={"private": "DO_NOT_REFLECT"}),
        ]
        for response in responses:

            def handle(request, response=response):
                good = self.handle(request)
                return response() if request.url.host == "portfolio.synthetic.example" else good

            with self.subTest(response=response):
                result = self.read(sources=self.make_sources(transport=httpx.MockTransport(handle)))
                self.assertEqual(result["mode"], "full")
                self.assertEqual(result["catalogue"]["groups"][0]["status"], "unavailable")
                self.assertEqual(result["catalogue"]["groups"][1]["status"], "available")
                self.assertNotIn("DO_NOT_REFLECT", json.dumps(result))

        for change in (
            lambda value: value.update(private="DO_NOT_REFLECT"),
            lambda value: value["projections"]["items"][0]["ref"].update(incarnation="foreign"),
        ):
            self.discovery_change = change
            result = self.read()
            self.assertEqual(result["mode"], "full")
            self.assertEqual(result["catalogue"]["groups"][0]["status"], "unavailable")
            self.assertNotIn("DO_NOT_REFLECT", json.dumps(result))

    def test_missing_config_never_uses_credentials_or_network_and_keeps_alias_absence_confirmed(
        self,
    ):
        with patch("socket.create_connection", side_effect=AssertionError("network")):
            result = self.read(
                sources=self.make_sources(
                    user_origin="",
                    portfolio_origin="",
                    signer_factory=lambda: self.fail("signer"),
                    token_factory=lambda *a, **k: self.fail("token"),
                )
            )
        self.assertEqual(result["mode"], "full")
        self.assertTrue(
            all(group["status"] == "unavailable" for group in result["catalogue"]["groups"])
        )
        self.assertEqual(result["displayNames"]["items"], [])

    def test_preexisting_deleted_fence_keeps_old_terminal_state_and_never_calls_portfolio(self):
        self.fence(reason="deleted")
        result = self.read()
        holdings = result["catalogue"]["groups"][0]["items"]
        self.assertEqual(
            (holdings[0]["ref"]["resourceId"], holdings[0]["state"]), (SOURCE, "deleted")
        )
        self.assertEqual(result["displayNames"]["items"], [])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.token_calls, [catalogue_fixture.USER])


if __name__ == "__main__":
    unittest.main()
