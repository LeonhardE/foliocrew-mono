"""Real signed archive disposal against the pinned User service and local frozen vault."""

import copy
import hashlib
import unittest
from contextlib import closing
from unittest.mock import patch

import httpx
import test_user_vault_authority as setup_authority
from fixtures import BOOT, UID

from app.retired_archive import cleanup_retired_archive
from app.store import SQLiteTransaction, document_path, private_resource_writer_fence_path
from app.user_vault_authority import ARCHIVE_RETIREMENT_PATH, ScopedUserVaults
from app.vaults import VaultService, _current
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import signing_input_fingerprint
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json, strict_json_loads
from folioview_shared.encrypted.legacy_archive import PROFILE
from folioview_shared.encrypted.private_resources import verify_private_registry_transition_payload


def digest(value):
    return hashlib.sha256(canonical_json(value)).hexdigest()


class RetiredArchiveTests(unittest.TestCase):
    def setUp(self):
        support = setup_authority.UserVaultAuthorityTests()
        support.setUp()
        self.addCleanup(support.doCleanups)
        self.support = support
        self.f = f = support.f
        self.store = support.store
        self.service = VaultService(self.store, clock=lambda: 1000)
        original = f.bootstrap()
        self.service.bootstrap(UID, original, BOOT)
        self.saved = original["archive"]
        self.path = document_path("hub_vaults", f.owner)
        self.fence_path = private_resource_writer_fence_path(f.owner)
        auth = support.authority
        change = verify_private_registry_transition_payload(
            auth["signedTransition"], f.root_public, f.root_id
        )
        change["archive"]["digest"] = digest(self.saved)
        auth["signedTransition"] = f.sign(change, "root")
        support.fence["transitionFingerprint"] = signing_input_fingerprint(auth["signedTransition"])
        self.store.transact(lambda unit: unit.put(self.fence_path, support.fence))
        # A later independent recovery can make the current User archive active again.
        auth["archive"] = {"state": "active", "digest": "f" * 64, "version": 4}
        command = f.sign(
            {
                "contractVersion": CONTRACT_VERSION,
                "profile": PROFILE,
                "ownerSubject": f.owner,
                "vaultId": f.vault,
                "rootKeyId": f.root_id,
                "action": "archive_delete",
                "stableOperationId": "test_retired_delete_0000001",
                "expectedVaultVersion": auth["vaultVersion"],
                "expectedLifecycleVersion": 0,
                "expectedArchiveRevision": 0,
                "expectedArchiveDigest": digest(self.saved),
                "registrySequence": auth["registry"]["registrySequence"],
                "checkpointDigest": auth["registry"]["checkpointDigest"],
                "keyEpoch": auth["registry"]["keyEpoch"],
                "issuedAt": 980,
                "expiresAt": 1050,
            },
            "root",
        )
        self.proof = {
            "command": command,
            "receipt": {
                "profile": PROFILE,
                "ownerSubject": f.owner,
                "rootKeyId": f.root_id,
                "vaultId": f.vault,
                "operationId": "test_retired_delete_0000001",
                "action": "archive_delete",
                "lifecycleVersion": 1,
                "archiveRevision": 1,
                "archiveDigest": digest(None),
                "commandFingerprint": signing_input_fingerprint(command),
                "acceptedAt": 990,
            },
        }
        support.wire.side_effect = self.respond
        self.scopes = ScopedUserVaults(self.store, owner=f.owner, client=support.client)

    def respond(self, request):
        value = strict_json_loads(request.content)
        self.assertEqual(str(request.url), self.support.user_origin + ARCHIVE_RETIREMENT_PATH)
        self.assertEqual(self.support.signer.sign.call_args.args[0]["aud"], str(request.url))
        self.assertEqual(request.headers["authorization"], "Bearer google.workload.identity")
        self.assertEqual(self.support.signer.sign.call_args.args[0]["jti"], value["nonce"])
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json", "X-FolioView-Contract": CONTRACT_VERSION},
            json={
                **{key: value[key] for key in ("contractVersion", "profile", "consumer", "nonce")},
                "requestDigest": hashlib.sha256(request.content).hexdigest(),
                "authority": self.support.authority,
                "retirement": self.proof,
            },
        )

    def run_cleanup(self, **options):
        return cleanup_retired_archive(
            self.service, UID, self.f.vault, scopes=self.scopes, **options
        )

    def test_retirement_preserves_recovery_and_public_history_across_retry(self):
        original = copy.deepcopy(self.support.authority)
        self.assertEqual(self.run_cleanup(apply=False)["remaining"], 1)
        self.assertEqual(
            self.store.transact(lambda unit: unit.get(self.path))["archive"], self.saved
        )
        self.assertEqual(self.run_cleanup()["remaining"], 0)
        stored = self.store.transact(lambda unit: _current(unit, self.f.owner, 1000)[0])
        self.assertIsNone(stored["archive"])
        self.assertEqual(stored["registryHistory"], [self.f.bundle])
        self.assertEqual(self.run_cleanup()["remaining"], 0)
        self.assertEqual(self.support.authority, original)
        with closing(self.store.connect()) as db:
            self.assertNotIn(
                self.saved["ciphertext"],
                str(db.execute("SELECT body FROM hub_documents").fetchall()),
            )

    def test_mismatched_receipt_missing_authority_and_partial_write_preserve_ciphertext(self):
        saved = copy.deepcopy(self.proof)
        self.proof["receipt"]["rootKeyId"] = "incorrect"
        with self.assertRaises(ContractError):
            self.run_cleanup()
        self.proof = None
        with self.assertRaises(ContractError):
            self.run_cleanup()
        self.proof = saved
        original_put = SQLiteTransaction.put

        def fail_after_proof(unit, path, value):
            if path == self.path:
                raise RuntimeError("synthetic lost connection")
            original_put(unit, path, value)

        with (
            patch.object(SQLiteTransaction, "put", fail_after_proof),
            self.assertRaises(RuntimeError),
        ):
            self.run_cleanup()
        proof_path = document_path("hub_operations", self.f.owner, "retired_archive", self.f.vault)
        self.assertIsNone(self.store.transact(lambda unit: unit.get(proof_path)))
        self.assertEqual(self.run_cleanup(apply=False)["remaining"], 1)
        # If the Hub writer changes after the remote acknowledgement, the read must be rejected.
        original = self.respond

        def race(request):
            self.store.transact(
                lambda u: u.put(self.fence_path, {**self.support.fence, "state": "frozen"})
            )
            return original(request)

        self.support.wire.side_effect = race
        with self.assertRaises(ContractError):
            self.run_cleanup()
        self.assertEqual(self.store.transact(lambda u: u.get(self.path))["archive"], self.saved)

    def test_rejects_modified_frozen_archive_and_attacker_supplied_scope(self):
        def changed(unit):
            row = unit.get(self.path)
            row["archive"]["ciphertext"] = "eHh4eHh4eHh4eHh4eHh4eA"
            unit.put(self.path, row)

        self.store.transact(changed)
        with self.assertRaises(ContractError):
            self.run_cleanup()
        with self.assertRaises(ContractError):
            cleanup_retired_archive(self.service, UID, "a_different_vault", scopes=self.scopes)
        with patch.object(self.scopes.client, "read", side_effect=AssertionError):
            self.assertEqual(
                cleanup_retired_archive(
                    self.service, "native-no-hub-copy", "native_vault", scopes=self.scopes
                )["remaining"],
                0,
            )
