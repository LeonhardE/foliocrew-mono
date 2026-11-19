"""Check real route retirement without legacy storage or identity verification."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from folioview_shared.encrypted.constants import CONTRACT_VERSION


class OwnerConnectionRolloutTests(unittest.TestCase):
    def test_old_flags_cannot_restore_legacy_owner_connection_routes(self):
        routes = (
            ("GET", "/api/v2/agent-capabilities"),
            ("GET", "/api/v2/agent-connections"),
            ("POST", "/api/v2/agent-connections/connection_A/revoke"),
            ("POST", "/api/v2/agent-connections/connection_A/grants/grant_A/revoke"),
        )
        headers = {
            "Authorization": "Bearer synthetic_owner",
            "X-FolioView-Contract": CONTRACT_VERSION,
        }
        with (
            patch.dict(os.environ, HUB_OAUTH_ENABLED="1", HUB_ENCRYPTED_ADAPTER_ENABLED="1"),
            patch("app.oauth.get_store", side_effect=AssertionError),
            patch("folioview_shared.auth.auth.verify_id_token", side_effect=AssertionError),
            TestClient(app) as client,
        ):
            for method, path in routes:
                with self.subTest(method=method, path=path):
                    response = client.request(
                        method,
                        path,
                        headers=headers,
                        json={"contractVersion": CONTRACT_VERSION} if method == "POST" else None,
                    )
                    self.assertEqual(response.status_code, 404, response.text)
                    self.assertEqual(response.headers["cache-control"], "no-store")

            current = client.get("/api/v2/persistent-account-authorizations/capabilities")
            self.assertEqual(current.status_code, 401, current.text)
            self.assertEqual(current.headers["cache-control"], "no-store")
