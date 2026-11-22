"""Reviewed static distribution and required local host-storage checks."""

import hashlib
import json
import os
import shutil
import subprocess
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import agent_client_assets as assets


class PrivateClientAssetTests(unittest.TestCase):
    def test_fixed_default_off_assets_no_queries_arbitrary_modules_or_secret_paths(self):
        app = FastAPI()
        app.include_router(assets.router)
        with TestClient(app) as client:
            with patch.object(assets, "agent_owned_enabled", return_value=False):
                for version in ("1.0.0", "1.0.1", "1.1.0", "1.2.0", "1.3.0", "1.3.1", "1.3.2"):
                    self.assertEqual(
                        client.get(f"/agent/v3/client/{version}/client.mjs").status_code, 503
                    )
            with patch.object(assets, "agent_owned_enabled", return_value=True):
                response = client.get("/agent/v3/client/1.3.2/client.mjs")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
                self.assertEqual(
                    assets.client_metadata()["sha256"], hashlib.sha256(response.content).hexdigest()
                )
                self.assertIn(assets.client_metadata()["sha256"], response.headers["ETag"])
                for version in ("1.0.0", "1.0.1", "1.1.0", "1.2.0", "1.3.0", "1.3.1", "1.3.2"):
                    for path in ("src/files.mjs", "index.mjs", "credentials.sqlite", "../../.env"):
                        self.assertEqual(
                            client.get(f"/agent/v3/client/{version}/" + path).status_code, 404
                        )
                    self.assertEqual(
                        client.get(
                            f"/agent/v3/client/{version}/client.mjs?origin=other"
                        ).status_code,
                        400,
                    )
                self.assertEqual(client.get("/agent/v3/client/1.0.2/client.mjs").status_code, 404)

    def test_original_version_remains_byte_identical_at_its_original_pin(self):
        app = FastAPI()
        app.include_router(assets.router)
        with (
            patch.object(assets, "agent_owned_enabled", return_value=True),
            TestClient(app) as client,
        ):
            response = client.get("/agent/v3/client/1.0.0/client.mjs")
            self.assertEqual(response.status_code, 200)
            original = "5b99a8fe60e12f39d05adf945251526da2651a3651c01e11975913926aabe77e"
            self.assertEqual(hashlib.sha256(response.content).hexdigest(), original)
            self.assertEqual(assets.client_metadata("1.0.0")["sha256"], original)
            self.assertNotEqual(original, assets.client_metadata()["sha256"])
            manifest = client.get("/agent/v3/client/1.0.0/integrity.json").json()
            notices = client.get("/agent/v3/client/1.0.0/THIRD_PARTY_NOTICES.md")
            self.assertEqual(manifest["clientVersion"], "1.0.0")
            self.assertEqual(manifest["files"]["dist/cli.mjs"], original)
            self.assertEqual(
                hashlib.sha256(notices.content).hexdigest(),
                manifest["files"]["THIRD_PARTY_NOTICES.md"],
            )

    def test_distribution_hashes_and_frozen_shared_dependency_are_complete(self):
        manifest = json.loads((assets.ROOT / "integrity.json").read_text())
        for file, expected in manifest["files"].items():
            self.assertEqual(
                hashlib.sha256((assets.ROOT / file).read_bytes()).hexdigest(), expected, file
            )
        lock = (assets.ROOT / "shared-contract.integrity.json").read_bytes()
        pinned = json.loads(lock)
        self.assertEqual(
            manifest["sharedLibrary"]["integritySha256"], hashlib.sha256(lock).hexdigest()
        )
        self.assertEqual(
            manifest["sharedLibrary"]["bundleSha256"], pinned["files"]["dist/core.mjs"]
        )
        self.assertEqual(manifest["nodeMinimum"], "24.12.0")
        self.assertIn("src/leases.mjs", pinned["files"])
        valuation_lock = (assets.ROOT / "valuation-contract.integrity.json").read_bytes()
        valuation = json.loads(valuation_lock)
        self.assertEqual(
            manifest["valuationLibrary"]["integritySha256"],
            hashlib.sha256(valuation_lock).hexdigest(),
        )
        self.assertEqual(
            manifest["valuationLibrary"]["holdingsSha256"], valuation["files"]["dist/holdings.mjs"]
        )
        self.assertEqual(valuation["frozenCoreSha256"], pinned["files"]["dist/core.mjs"])
        self.assertEqual(manifest["valuationLibrary"]["schemaSha256"], valuation["schemaSha256"])
        self.assertLessEqual(
            (assets.ROOT / "dist/cli.mjs").stat().st_size, assets.FILES["client.mjs"][2]
        )

    def test_previous_task_center_client_keeps_its_exact_versioned_download(self):
        app = FastAPI()
        app.include_router(assets.router)
        with (
            patch.object(assets, "agent_owned_enabled", return_value=True),
            TestClient(app) as client,
        ):
            response = client.get("/agent/v3/client/1.2.0/client.mjs")
            self.assertEqual(response.status_code, 200)
            original = "8d516f977bc994cb728b2d57902ff8b132a9428756ef35db7cbb033b3b0b0471"
            self.assertEqual(hashlib.sha256(response.content).hexdigest(), original)
            self.assertEqual(assets.client_metadata("1.2.0")["sha256"], original)
            self.assertNotEqual(assets.client_metadata()["sha256"], original)
            self.assertEqual(assets.client_metadata()["version"], "1.3.2")

    def test_130_source_distribution_and_manifest_remain_at_their_original_pins(self):
        root = assets.ROOT / "releases" / "1.3.0"
        manifest_bytes = (root / "integrity.json").read_bytes()
        self.assertEqual(
            hashlib.sha256(manifest_bytes).hexdigest(),
            "2bbfef3bda0862037dd0470b1f02325a70fc69a0347d262a818f85aa8c6b27b8",
        )
        manifest = json.loads(manifest_bytes)
        self.assertEqual(manifest["clientVersion"], "1.3.0")
        for file, expected in manifest["files"].items():
            self.assertEqual(hashlib.sha256((root / file).read_bytes()).hexdigest(), expected)
        original = "20b1ce199a8ac8ac334c91dde120444fdd11397e879dbf98e3de6b586b59c290"
        self.assertEqual(assets.client_metadata("1.3.0")["sha256"], original)
        app = FastAPI()
        app.include_router(assets.router)
        with (
            patch.object(assets, "agent_owned_enabled", return_value=True),
            TestClient(app) as client,
        ):
            response = client.get("/agent/v3/client/1.3.0/client.mjs")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(hashlib.sha256(response.content).hexdigest(), original)
            self.assertEqual(response.headers["ETag"], '"sha256-' + original + '"')
            self.assertNotEqual(assets.client_metadata()["sha256"], original)

    def test_131_original_manifest_and_download_remain_at_their_pins(self):
        root = assets.ROOT / "releases" / "1.3.1"
        manifest_bytes = (root / "integrity.json").read_bytes()
        self.assertEqual(
            hashlib.sha256(manifest_bytes).hexdigest(),
            "ee880553b33027174983e3532e9483946588c11f3b575289d92a5fce5ac9b992",
        )
        manifest = json.loads(manifest_bytes)
        self.assertEqual(manifest["clientVersion"], "1.3.1")
        for file, expected in manifest["files"].items():
            self.assertEqual(hashlib.sha256((root / file).read_bytes()).hexdigest(), expected, file)
        self.assertEqual(
            manifest["sharedLibrary"]["bundleSha256"],
            "9154f84d3d03af2edb98cbb6471285b0ff12f03e39a51d501b5a0142458aecd4",
        )
        self.assertEqual(
            assets.client_metadata("1.3.1")["sha256"],
            "697478fe74675a8bb6cfca4f0916a899dcd3eb860a5d4c33b7ef697163ba342c",
        )

    def test_132_retains_asset_budget_and_node_requirement(self):
        self.assertEqual(assets.FILES["client.mjs"][2], 2 * 1024 * 1024)
        self.assertLessEqual((assets.ROOT / "dist/cli.mjs").stat().st_size, 2 * 1024 * 1024)
        self.assertEqual(assets.client_metadata()["nodeMinimum"], "24.12.0")

    def test_private_file_loss_corruption_permissions_and_explicit_reauthorization(self):
        node = os.getenv("FOLIOVIEW_NODE_BIN") or shutil.which("node")
        self.assertIsNotNone(node, "Node 24 is required; do not skip host credential validation")
        result = subprocess.run(
            [node, "--test", str(assets.ROOT / "tests/files.test.mjs")],
            capture_output=True,
            text=True,
            timeout=25,
            env={**os.environ, "NODE_OPTIONS": ""},
        )
        self.assertEqual(result.returncode, 0, result.stderr[:1500] + result.stdout[-1500:])
        self.assertIn("pass 4", result.stdout)

    def test_cli_distinguishes_policy_time_state_service_and_credential_failures(self):
        node = os.getenv("FOLIOVIEW_NODE_BIN") or shutil.which("node")
        self.assertIsNotNone(node, "Node 24 is required for CLI recovery validation")
        result = subprocess.run(
            [node, "--test", str(assets.ROOT / "tests/cli.test.mjs")],
            capture_output=True,
            text=True,
            timeout=25,
            env={**os.environ, "NODE_OPTIONS": ""},
        )
        self.assertEqual(result.returncode, 0, result.stderr[:1500] + result.stdout[-1500:])
        self.assertIn("pass 6", result.stdout)
