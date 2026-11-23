"""Exercise the branded edge through actual Hub HTTP and MCP entry points."""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app.agent_client_assets import FILES, VERSION
from app.main import app
from app.native_origin import BRAND_ORIGIN, PROOF_HEADER, PROOF_VERSION
from app.store import SQLiteHubStore
from folioview_shared.encrypted.jsonutil import b64url_encode

PRIMARY = "https://synthetic-run.example"
PROTECTED = "/.well-known/oauth-protected-resource/mcp/v3"
MCP = "/mcp/v3"


class BrandedNativeOriginTests(unittest.TestCase):
    def setUp(self):
        scratch = self.enterContext(tempfile.TemporaryDirectory())
        store = SQLiteHubStore(Path(scratch) / "scope.sqlite3")
        self.key = Ed25519PrivateKey.generate()
        self.enterContext(
            patch.dict(
                os.environ,
                {
                    "HUB_NATIVE_EDGE_PUBLIC_KEY": b64url_encode(
                        self.key.public_key().public_bytes_raw()
                    ),
                    "HUB_OAUTH_ENABLED": "1",
                    "HUB_OAUTH_ISSUER": PRIMARY,
                    "HUB_OAUTH_CONSENT_URL": PRIMARY + "/oauth/consent",
                    "HUB_OAUTH_CLIENTS_JSON": json.dumps(
                        [
                            {
                                "provider": "chatgpt",
                                "clientId": "synthetic_client",
                                "redirectUris": ["https://owner.example/callback"],
                                "tokenEndpointAuthMethod": "none",
                                "secretSha256": None,
                            }
                        ]
                    ),
                    "HUB_PERSISTENT_TRANSPORT_ENABLED": "1",
                    "HUB_PERSISTENT_MCP_ENABLED": "1",
                    "HUB_AGENT_OWNED_CREDENTIALS_ENABLED": "1",
                    "HUB_PERSISTENT_RESOURCE_CONSENTS_ENABLED": "1",
                    "HUB_PERSISTENT_PUBLICATIONS_ENABLED": "1",
                    "HUB_PERSISTENT_EXECUTION_ENABLED": "1",
                    "HUB_AGENT_OWNER_URL": "https://owner.example/agents",
                    "CORS_ORIGINS": "https://owner.example",
                },
            )
        )
        self.enterContext(patch("app.native_transport_routes.get_store", return_value=store))
        self.client = self.enterContext(TestClient(app, base_url=PRIMARY))

    def proof(self, method, target, *, origin=None, offset=0):
        stamp = str(int(time.time()) + offset)
        payload = json.dumps(
            [PROOF_VERSION, stamp, PRIMARY, BRAND_ORIGIN, method, target, origin],
            separators=(",", ":"),
        ).encode()
        return {PROOF_HEADER.decode(): stamp + "." + b64url_encode(self.key.sign(payload))}

    def test_each_discovery_challenge_and_account_config_uses_its_own_origin(self):
        for origin, headers in (
            (PRIMARY, {}),
            (BRAND_ORIGIN, self.proof("GET", PROTECTED)),
        ):
            response = self.client.get(PROTECTED, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["resource"], origin + MCP)
            self.assertEqual(response.json()["resource_name"], "Foliocrew")
            self.assertEqual(
                response.json()["authorization_servers"], [origin + "/oauth/persistent"]
            )
            challenge = self.client.post(
                MCP, headers=self.proof("POST", MCP) if origin == BRAND_ORIGIN else {}
            )
            self.assertEqual(challenge.status_code, 401)
            self.assertIn(origin + PROTECTED, challenge.headers["www-authenticate"])
            path = "/agent/v3/account/config"
            config = self.client.get(
                path, headers=self.proof("GET", path) if origin == BRAND_ORIGIN else {}
            )
            self.assertEqual(config.status_code, 200)
            self.assertEqual(config.json()["issuer"], origin)
        self.assertEqual(self.client.get(PROTECTED).json()["resource"], PRIMARY + MCP)

    def test_missing_replayed_or_modified_proof_cannot_choose_branded_origin(self):
        for path, headers in (
            (PROTECTED, {"host": "mcp.foliocrew.app"}),
            (PROTECTED + "?changed=1", self.proof("GET", PROTECTED)),
            (PROTECTED, self.proof("POST", PROTECTED)),
            (PROTECTED, self.proof("GET", PROTECTED, offset=-31)),
            (PROTECTED, {**self.proof("GET", PROTECTED), "origin": BRAND_ORIGIN}),
        ):
            response = self.client.get(path, headers=headers)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(
            self.client.get("/health", headers=self.proof("GET", "/health")).status_code, 404
        )
        with patch.dict(os.environ, {"HUB_NATIVE_EDGE_PUBLIC_KEY": ""}):
            self.assertEqual(
                self.client.get(PROTECTED, headers=self.proof("GET", PROTECTED)).status_code, 403
            )
            self.assertEqual(self.client.get(PROTECTED).status_code, 200)

    def test_latest_client_and_previous_pin_download_through_verified_edge(self):
        for version in ("1.3.1", "1.3.2", VERSION):
            for asset in FILES:
                path = f"/agent/v3/client/{version}/{asset}"
                with self.subTest(path=path):
                    branded = self.client.get(path, headers=self.proof("GET", path))
                    self.assertEqual(branded.status_code, 200)
                    direct = self.client.get(path)
                    self.assertEqual(direct.status_code, 200)
                    self.assertEqual(branded.content, direct.content)
        unknown = "/agent/v3/client/1.3.4/client.mjs"
        self.assertEqual(
            self.client.get(unknown, headers=self.proof("GET", unknown)).status_code, 404
        )
        path = f"/agent/v3/client/{VERSION}/client.mjs"
        self.assertEqual(self.client.post(path, headers=self.proof("POST", path)).status_code, 404)
