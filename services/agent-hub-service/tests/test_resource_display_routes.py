"""Closed Owner GET integration, preserving all three original route contracts."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from fixtures import BOOT, OTHER_UID, SOURCE, UID, VaultFixture
from test_resource_display import Sources

from app.api import get_service, require_owner
from app.catalogue import get_sources
from app.main import app
from app.private_display_name_routes import get_display_names
from app.private_display_names import PrivateDisplayNameService
from app.resource_display import PROFILE, ResourceDisplayService
from app.store import SQLiteHubStore
from app.vaults import VaultService
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.schema import validate_schema


class ResourceDisplayRoutesTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.vaults = VaultService(
            SQLiteHubStore(Path(directory.name) / "display.sqlite"), clock=lambda: 1000
        )
        self.f = VaultFixture()
        self.vaults.bootstrap(UID, self.f.bootstrap(), BOOT)
        self.vaults.create_source(
            UID,
            self.f.vault,
            SOURCE,
            self.f.control(),
            "synthetic_source_create_0001",
            self.f.kid("device_sig"),
        )
        self.sources = Sources()

        def owner(request: Request):
            uid = {"Bearer synthetic-A": UID, "Bearer synthetic-B": OTHER_UID}.get(
                request.headers.get("authorization")
            )
            if uid is None:
                raise HTTPException(401, "Sign-in required")
            return SimpleNamespace(uid=uid)

        app.dependency_overrides[require_owner] = owner
        app.dependency_overrides[get_service] = lambda: self.vaults
        app.dependency_overrides[get_sources] = lambda: self.sources
        app.dependency_overrides[get_display_names] = lambda: PrivateDisplayNameService(
            self.vaults.store, clock=lambda: 1000
        )
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.path = "/api/v3/resources/display"
        self.headers = {
            "Authorization": "Bearer synthetic-A",
            "X-FolioView-Contract": CONTRACT_VERSION,
        }

    def test_full_owner_composition_and_original_gets_remain_exact_and_no_store(self):
        response = self.client.get(self.path, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text[:200])
        self.assertEqual(response.headers["cache-control"], "no-store")
        value = response.json()
        self.assertEqual((value["profile"], value["mode"]), (PROFILE, "full"))
        for field, path in (
            ("catalogue", "/api/v2/resources/catalogue"),
            ("displayNameCapabilities", "/api/v3/private-display-names/capabilities"),
            ("displayNames", f"/api/v3/private-display-names/{self.f.vault}/holdings"),
        ):
            result = self.client.get(path, headers=self.headers)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.headers["cache-control"], "no-store")
            self.assertEqual(value[field], result.json())

    def test_queries_duplicate_contract_identity_headers_and_nonempty_get_body_are_closed(self):
        cases = [
            {"url": self.path + "?owner=foreign"},
            {"url": self.path + "?vaultId=" + self.f.vault},
            {"headers": {**self.headers, "X-FolioView-Contract": "v1"}},
            {"headers": {"Authorization": "Bearer synthetic-A"}},
            {"headers": [*self.headers.items(), ("X-FolioView-Contract", CONTRACT_VERSION)]},
            {"headers": {**self.headers, "Idempotency-Key": BOOT}},
            {"headers": {**self.headers, "X-FolioView-Author-Key": "A" * 43}},
            {"headers": {**self.headers, "X-FolioView-Delegation": "foreign"}},
            {"headers": {**self.headers, "X-FolioView-Authority-Delegation": "foreign"}},
            {"headers": {**self.headers, "X-Serverless-Authorization": "Bearer a.b.c"}},
            {"content": b"{}"},
            {"content": b" "},
        ]
        for case in cases:
            with self.subTest(case=case):
                with patch.object(
                    ResourceDisplayService,
                    "read",
                    side_effect=AssertionError("service must not be called"),
                ):
                    result = self.client.request(
                        "GET", **{"url": self.path, "headers": self.headers, **case}
                    )
                self.assertIn(result.status_code, (400, 403))
                self.assertEqual(result.headers["cache-control"], "no-store")
                validate_schema("Error", result.json())
        self.assertEqual(self.sources.calls, 0)

    def test_unsupported_methods_and_private_failures_are_closed_no_store_errors(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            response = self.client.request(method, self.path, headers=self.headers)
            # The existing formal Error boundary maps unsupported methods to
            # its closed malformed_request status rather than a new wire code.
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.headers["cache-control"], "no-store")
            validate_schema("Error", response.json())
        with patch.object(
            ResourceDisplayService, "read", side_effect=RuntimeError("PRIVATE_STORAGE_ERROR")
        ):
            result = self.client.get(self.path, headers=self.headers)
        self.assertEqual(result.status_code, 503)
        validate_schema("Error", result.json())
        self.assertNotIn("PRIVATE_STORAGE_ERROR", result.text)
        self.assertEqual(self.sources.calls, 0)

    def test_other_owner_keeps_original_no_vault_gets_but_cannot_select_first_owners_scope(
        self,
    ):
        headers = {**self.headers, "Authorization": "Bearer synthetic-B"}
        response = self.client.get(self.path, headers=headers)
        self.assertEqual(response.status_code, 404)
        validate_schema("Error", response.json())
        self.assertEqual(self.sources.calls, 0)
        catalogue = self.client.get("/api/v2/resources/catalogue", headers=headers)
        self.assertEqual(catalogue.status_code, 200)
        self.assertEqual(catalogue.json()["groups"][0]["status"], "uninitialized")
        caps = self.client.get("/api/v3/private-display-names/capabilities", headers=headers)
        self.assertEqual(caps.status_code, 200)
        self.assertTrue(caps.json()["enabled"])

    def test_actual_owner_dependency_refuses_missing_duplicate_and_non_google_tokens_before_storage(
        self,
    ):
        app.dependency_overrides.pop(require_owner)
        with (
            patch("socket.create_connection", side_effect=AssertionError("network")),
            patch.object(ResourceDisplayService, "read", side_effect=AssertionError("service")),
        ):
            for headers in ({}, [("Authorization", "Bearer a"), ("Authorization", "Bearer b")]):
                response = self.client.get(self.path, headers=headers)
                self.assertEqual(response.status_code, 401)
                validate_schema("Error", response.json())
            with (
                patch("folioview_shared.auth._get_firebase_app", return_value=object()),
                patch(
                    "folioview_shared.auth.auth.verify_id_token",
                    return_value={"uid": UID, "firebase": {"sign_in_provider": "custom"}},
                ),
            ):
                for token in ("synthetic-agent-token", "synthetic-workload-token"):
                    response = self.client.get(
                        self.path, headers={**self.headers, "Authorization": "Bearer " + token}
                    )
                    self.assertEqual(response.status_code, 401)
                    validate_schema("Error", response.json())
        self.assertEqual(self.sources.calls, 0)


if __name__ == "__main__":
    unittest.main()
