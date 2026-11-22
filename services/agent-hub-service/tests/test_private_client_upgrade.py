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
from folioview_shared.encrypted.agent_credentials import approve_credential
from folioview_shared.encrypted.crypto import _signed_parts, signing_input_fingerprint
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

    def test_pending_130_handoff_activates_after_upgrade_without_replacing_private_keys(self):
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

    def test_native_activation_verifies_transferred_start_and_original_approval_prefix(self):
        self.execution()
        fixture = self.f
        old_digest = "a" * 64
        owner_keys = {
            name: cert
            for name, cert in fixture.certificates.items()
            if cert["connectionId"] is None
        }
        first = fixture.make_bundle(
            certificates=owner_keys,
            sequence=28,
            issued_at=900,
            checkpoint_overrides={"previousDigest": old_digest},
        )
        start_registry = fixture.verify(first)
        approved = fixture.make_bundle(previous=start_registry, issued_at=1000)
        approved_registry = fixture.verify(approved, previous=start_registry)
        current = fixture.make_bundle(previous=approved_registry, issued_at=1001)
        start = {
            "registryEpoch": 2,
            "registrySequence": start_registry.registry_sequence,
            "checkpointDigest": start_registry.checkpoint_digest,
            "keyEpoch": 1,
        }
        transition = fixture.sign(
            {
                "contractVersion": self.activation["contractVersion"],
                "profile": "folioview.owner-registry-transition.v1",
                "ownerSubject": fixture.owner,
                "vaultId": fixture.vault,
                "rootKeyId": fixture.root_id,
                "operationId": "synthetic_client_registry_transition",
                "previousVaultVersion": 27,
                "nextVaultVersion": 28,
                "previousHead": {
                    "registryEpoch": 1,
                    "registrySequence": 27,
                    "checkpointDigest": old_digest,
                    "keyEpoch": 1,
                },
                "nextHead": start,
                "ownerKeyIds": sorted(cert["keyId"] for cert in owner_keys.values()),
                "archive": {"state": "active", "version": 1, "digest": "b" * 64},
                "issuedAt": 900,
            },
            "root",
        )
        pin = {
            "registrySequence": approved_registry.registry_sequence,
            "checkpointDigest": approved_registry.checkpoint_digest,
        }
        _, original_binding = _signed_parts(self.activation["binding"])
        binding = fixture.sign({**original_binding, **pin})
        fingerprint = signing_input_fingerprint(binding)
        identity = {**self.activation["identity"], "bindingFingerprint": fingerprint}
        _, original_approval = _signed_parts(self.activation["approval"])
        approval = fixture.sign({**original_approval, **pin, "bindingFingerprint": fingerprint})
        lease = approve_credential(
            approval,
            registry=approved_registry,
            identity=identity,
            current_lease=None,
            setup_intent_id=self.activation["setupIntentId"],
            audience=sessions.ORIGIN,
            now=1000,
        )
        self.activation.update(
            identity=identity,
            binding=binding,
            approval=approval,
            lease=lease,
            anchor={"rootKeyId": fixture.root_id, **pin},
        )
        session = {
            "identity": identity,
            "binding": binding,
            "rootJwk": fixture.root_public,
            "registryHistory": [first, approved, current],
            "registryStartProof": {"start": start, "signedTransition": transition},
            "registrySequence": 30,
            "credentialLease": lease,
            "credentialApproval": approval,
            "provider": self.activation["provider"],
            "consent": None,
            "consentOperations": [],
        }

        def read_session(request):
            self.assertEqual(request["path"], self.base + "/session")
            return {"value": session}

        self.handle = read_session
        self.upgrade()
        self.peer.call("clock", {"now": 1001})
        self.assertEqual(self.peer.call("activate", self.response())["state"], "connected")
        self.assertEqual(self.peer.call("initialize")["registrySequence"], 30)
        self.assertEqual(self.state()["active"]["pins"]["registrySequence"], 30)

    def test_active_130_profile_and_original_sealed_outbox_survive_upgrade(self):
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

    def test_upgraded_client_seals_maximum_newline_section_and_retains_report_policy(self):
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
