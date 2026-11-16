"""Real old/new standalone clients reuse synthetic private state and original authority."""

import json
import os
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import private_client_fixture as sessions
import test_private_host_client as hosts
from fixtures import UID
from test_oauth import TASK
from test_persistent_content import PersistentContentFixture

from app.persistent_results import PersistentOwnerResultService
from folioview_shared.encrypted.crypto import _signed_parts
from folioview_shared.encrypted.persistent_content import open_persistent_content


class PrivateClientUpgradeTests(unittest.TestCase):
    configure_execution = hosts.PrivateHostClientTests.configure_execution
    handle = hosts.PrivateHostClientTests.handle
    execution = hosts.PrivateHostClientTests.execution
    facts_carrier = hosts.PrivateHostClientTests.facts_carrier
    response = hosts.PrivateHostClientTests.response

    def setUp(self):
        with patch.dict(os.environ, {"FOLIOVIEW_TEST_NATIVE_CLIENT_RELEASE": "1.3.0"}):
            hosts.PrivateHostClientTests.setUp(self)

    def state(self):
        paths = list(Path(self.directory).glob("*/credentials.sqlite"))
        self.assertEqual(len(paths), 1)
        with sqlite3.connect(paths[0]) as connection:
            return json.loads(
                connection.execute("SELECT value FROM state WHERE id=1").fetchone()[0]
            )

    def upgrade(self):
        self.peer.close()
        self.peer = sessions.RuntimePeer(self.handle, "private_host_peer.mjs")
        self.addCleanup(self.peer.close)
        self.peer.call(
            "load", {"directory": self.directory, "actor": self.actor, "provider": "muse"}
        )

    def test_pending_130_handoff_activates_in_131_without_replacing_private_keys(self):
        self.execution()
        pending = self.state()["pending"]
        self.upgrade()
        self.assertEqual(self.peer.call("activate", self.response())["state"], "connected")
        self.assertEqual(self.peer.call("initialize")["state"], "connected")
        current = self.state()
        self.assertIsNone(current["pending"])
        for field in ("signingPrivateJwk", "encryptionPrivateJwk"):
            self.assertEqual(current["active"][field], pending["profile"][field])
        self.assertEqual(current["active"]["activation"]["lease"], self.activation["lease"])

    def test_active_130_profile_and_original_sealed_outbox_survive_131_upgrade(self):
        self.execution()
        self.peer.call("activate", self.response())
        self.peer.call("initialize")
        run = self.peer.call("begin", {"taskId": TASK, "triggerId": "native_upgrade_run_0001"})
        self.peer.call(
            "input", {"runId": run["runId"], "publicationId": run["inputs"][0]["publicationId"]}
        )
        report = PersistentContentFixture.private_content(
            self.f, PersistentContentFixture.content_context(self.f, "result_revision")
        )["payload"]
        self.drop_next_report = True
        denied = self.peer.call("submit", {"runId": run["runId"], "report": report}, ok=False)
        self.assertEqual(denied["error"], "runtime_network_unavailable")
        original = self.state()
        outbox = {k: v for k, v in original["records"].items() if k.startswith("outbox:")}
        self.assertTrue(outbox)
        self.upgrade()
        self.assertEqual(self.peer.call("initialize")["state"], "connected")
        resumed = self.state()
        self.assertEqual(resumed["active"], original["active"])
        self.assertEqual({k: resumed["records"][k] for k in outbox}, outbox)
        saved = self.peer.call("submit", {"runId": run["runId"], "report": {"changed": True}})
        self.assertEqual(saved["state"], "saved")
        self.assertEqual(self.ciphertexts[0], self.ciphertexts[1])
        stored = PersistentOwnerResultService(self.fx.store, clock=lambda: self.fx.now).owner_get(
            UID, self.f.vault, saved["resultId"]
        )
        _, proof = _signed_parts(stored["envelope"]["proof"])
        opened = open_persistent_content(
            stored["envelope"]["jwe"], self.f.keys["recovery_enc"], context=proof["context"]
        )
        self.assertEqual(opened["payload"], report)
        self.fx.now = 4000
        self.peer.call("clock", {"now": 4000})
        self.assertEqual(
            self.peer.call("initialize", ok=False)["error"], "key_authorization_required"
        )

    def test_131_seals_maximum_newline_section_and_retains_report_policy(self):
        self.execution()
        self.peer.call("activate", self.response())
        self.upgrade()
        self.peer.call("initialize")
        run = self.peer.call("begin", {"taskId": TASK, "triggerId": "native_upgrade_report_0001"})
        self.peer.call(
            "input", {"runId": run["runId"], "publicationId": run["inputs"][0]["publicationId"]}
        )
        report = PersistentContentFixture.private_content(
            self.f, PersistentContentFixture.content_context(self.f, "result_revision")
        )["payload"]
        report["sections"][0]["markdown"] = "[x](javascript:bad)"
        denied = self.peer.call("submit", {"runId": run["runId"], "report": report}, ok=False)
        self.assertEqual(denied["error"], "invalid_report")
        self.assertEqual(self.ciphertexts, [])
        report["sections"][0]["markdown"] = "\n" * 16384
        saved = self.peer.call("submit", {"runId": run["runId"], "report": report})
        stored = PersistentOwnerResultService(self.fx.store, clock=lambda: self.fx.now).owner_get(
            UID, self.f.vault, saved["resultId"]
        )
        _, proof = _signed_parts(stored["envelope"]["proof"])
        opened = open_persistent_content(
            stored["envelope"]["jwe"], self.f.keys["recovery_enc"], context=proof["context"]
        )
        self.assertEqual(opened["payload"], report)
