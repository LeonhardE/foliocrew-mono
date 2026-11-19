"""Check exact User-side vault baseline staging before a writer handover."""

import hashlib
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

from test_private_recovery import OWNER, VAULT, registry_fixture

from app.private_resources.legacy_baselines import (
    COLLECTION,
    LegacyVaultBaselines,
    verified_baseline,
)
from app.private_resources.original_operations import original_operation_baseline
from app.private_resources.recovery import RecoveryHeads
from app.resources import FirestoreUserResourceStore, SQLiteUserResourceStore
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import b64url_encode, canonical_json, strict_json_loads


class LegacyVaultBaselineTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.store = SQLiteUserResourceStore(str(Path(work.name) / "legacy.db"))
        self.baselines = LegacyVaultBaselines(self.store)
        _, root, _, registry, bundle, _ = registry_fixture()
        scope = {"ownerSubject": OWNER, "vaultId": VAULT, "rootKeyId": registry.root_key_id}
        self.vault = {
            **scope,
            "rootJwk": root,
            "sources": [],
            "operationCount": 1,
            "version": 1,
            "registryHistory": [bundle],
            "archive": {
                **scope,
                "profile": "folioview.passkey-vault.v1",
                "credentialId": b64url_encode(b"synthetic_credential"),
                "prfSalt": b64url_encode(b"s" * 32),
                "iv": b64url_encode(b"i" * 12),
                "ciphertext": b64url_encode(b"encrypted_archive_fixture"),
            },
        }
        self.body = verified_baseline(OWNER, self.vault, None, now=1000)
        self.digest = hashlib.sha256(self.body).hexdigest()

    def stage(self, store=None, *, vault=None, owner=OWNER, digest=None):
        return (store or self.baselines).stage(
            owner,
            vault or self.vault,
            None,
            expected_digest=digest or self.digest,
            now=1000,
        )

    def test_readback_preserves_archive_without_publishing_the_shadow_head(self):
        self.assertTrue(self.stage())
        self.assertFalse(self.stage())
        read = self.baselines.read(OWNER, VAULT, self.digest)
        self.assertEqual(read, self.body)
        body = strict_json_loads(read)
        self.assertEqual(body["archive"], self.vault["archive"])
        self.assertEqual(body["registry"]["registrySequence"], 1)
        self.assertNotIn("registryHistory", body)
        self.assertIsNone(RecoveryHeads(self.store).read(OWNER))
        self.assertIsNone(self.baselines.read("1" * 64, VAULT, self.digest))
        self.assertIsNone(self.baselines.read(OWNER, "other_vault", self.digest))

    def test_conflicting_input_and_corrupt_copy_leave_no_replacement(self):
        with self.assertRaisesRegex(ContractError, "recipient_binding_mismatch"):
            self.stage(owner="1" * 64)
        with self.assertRaisesRegex(ContractError, "version_conflict"):
            self.stage(digest="0" * 64)
        candidate = deepcopy(self.vault)
        candidate["registryHistory"][0]["checkpoint"]["signature"] = "A" * 86
        with self.assertRaisesRegex(ContractError, "invalid_signature"):
            self.stage(vault=candidate)
        self.assertTrue(self.stage())
        with self.store.connection() as db:
            db.execute(f"UPDATE {COLLECTION} SET body=?", (b"wrong",))
        with self.assertRaisesRegex(ContractError, "version_conflict"):
            self.stage()
        with self.assertRaisesRegex(ContractError, "authorization_unavailable"):
            self.baselines.read(OWNER, VAULT, self.digest)

    def test_firestore_uses_create_only_and_checks_exact_replays(self):
        store = Mock(spec=FirestoreUserResourceStore)
        store.client = Mock(_database="user-data")
        reference = store.client.collection.return_value.document.return_value
        transaction = Mock()
        reference.get.return_value.exists = False
        baselines = LegacyVaultBaselines(store)
        with (
            patch("app.private_resources.legacy_baselines.firestore.transactional", lambda fn: fn),
            patch(
                "app.private_resources.legacy_baselines.BoundedTransaction",
                return_value=transaction,
            ),
        ):
            self.assertTrue(self.stage(store=baselines))
            transaction.create.assert_called_once_with(reference, {"body": self.body})
            reference.get.return_value.exists = True
            reference.get.return_value.to_dict.return_value = {"body": self.body}
            self.assertFalse(self.stage(store=baselines))
            transaction.create.assert_called_once()
            reference.get.return_value.to_dict.return_value = {"body": b"different"}
            with self.assertRaisesRegex(ContractError, "version_conflict"):
                self.stage(store=baselines)
            transaction.create.assert_called_once()


class OriginalOperationBaselineTests(unittest.TestCase):
    def test_scoped_original_keys_and_types_survive_retry_without_becoming_live(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = SQLiteUserResourceStore(str(Path(temporary.name) / "receipts.sqlite3"))
        baselines = LegacyVaultBaselines(store)
        _, root, _, registry, _, _ = registry_fixture()
        ref = {
            "kind": "holdings",
            "sourceService": "portfolio",
            "resourceId": "source_A",
            "incarnation": "inc_A",
        }
        scope = {
            "ownerSubject": OWNER,
            "vaultId": VAULT,
            "rootJwk": root,
            "rootKeyId": registry.root_key_id,
            "sources": [{"resourceRef": ref, "sourceEpoch": 1}],
        }
        mutation = "synthetic_archive_source_mutation"
        path = hashlib.sha256(canonical_json([OWNER, "portfolio", mutation])).hexdigest()
        request = {
            "contractVersion": CONTRACT_VERSION,
            "ownerSubject": OWNER,
            "mutationId": mutation,
            "ref": ref,
            "expectedSourceEpoch": 1,
            "newSourceEpoch": 2,
            "reason": "deleted",
        }
        ack = {
            "contractVersion": CONTRACT_VERSION,
            "mutationId": mutation,
            "ref": ref,
            "acknowledgedSourceEpoch": 2,
            "acknowledgedAt": "2026-11-19T05:00:00Z",
        }
        source = {
            "request": request,
            "ack": ack,
            "fingerprint": hashlib.sha256(canonical_json(request)).hexdigest(),
        }

        def typed(value):
            if type(value) is dict:
                return {"mapValue": {"fields": {key: typed(item) for key, item in value.items()}}}
            if type(value) is int:
                return {"integerValue": str(value)}
            return {"stringValue": value}

        records = {
            f"hub_fence_mutations/{path}": typed(source)["mapValue"]["fields"],
            f"hub_operations/{'a' * 64}": typed(
                {"ownerSubject": OWNER, "kind": "registry", "fingerprint": "f" * 64}
            )["mapValue"]["fields"],
        }
        body = original_operation_baseline(OWNER, scope, records)
        expected = hashlib.sha256(body).hexdigest()
        self.assertTrue(
            baselines.stage_original_operations(OWNER, scope, records, expected_digest=expected)
        )
        self.assertFalse(
            baselines.stage_original_operations(OWNER, scope, records, expected_digest=expected)
        )
        read = strict_json_loads(baselines.read(OWNER, VAULT, expected))
        self.assertEqual(read["originalOperations"], records)
        self.assertIsNone(RecoveryHeads(store).read(OWNER))
        altered = deepcopy(records)
        altered[f"hub_fence_mutations/{path}"]["ack"]["mapValue"]["fields"][
            "acknowledgedSourceEpoch"
        ]["integerValue"] = "3"
        with self.assertRaisesRegex(ContractError, "authorization_unavailable"):
            baselines.stage_original_operations(OWNER, scope, altered, expected_digest=expected)
