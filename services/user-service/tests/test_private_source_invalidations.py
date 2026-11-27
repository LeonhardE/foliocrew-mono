"""Exercise the complete private source acknowledgement transaction."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from test_private_recovery import OWNER, UID, VAULT, projection
from test_private_report_sources import live_projection

from app.main import app
from app.private_resources.api import PORTFOLIO_FENCE_PATH, portfolio_invalidation
from app.private_resources.recovery import COLLECTION as HEADS
from app.private_resources.report_sources import (
    HOLDINGS_FENCES,
    ReportSourceAuthority,
    holdings_fence_key,
)
from app.private_resources.source_invalidations import (
    INVALIDATION_RECEIPTS,
    SOURCE_INDEX,
    PortfolioSourceRevision,
    SourceInvalidations,
    invalidation_receipt_key,
)
from app.resources import FirestoreUserResourceStore, SQLiteUserResourceStore
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json
from folioview_shared.encrypted.private_resources import REPORT_PROFILE, source_index_digest
from folioview_shared.service_identity import UntrustedServiceCaller


class SourceInvalidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = SQLiteUserResourceStore(str(Path(temporary.name) / "user.sqlite"))
        self.now = 1460
        self.writer = SourceInvalidations(self.store, clock=lambda: self.now)
        self.ref = {
            "kind": "holdings",
            "sourceService": "portfolio",
            "resourceId": "synthetic_holdings",
            "incarnation": "incarnation_a",
        }
        self.binding = {"ref": self.ref, "sourceEpoch": 2}
        self.fence_key = holdings_fence_key(OWNER, VAULT, self.ref["resourceId"])
        self.fence = {
            "ownerSubject": OWNER,
            "vaultId": VAULT,
            "binding": self.binding,
            "state": "eligible",
            "currentRevision": 3,
        }
        self.index = {
            "ownerSubject": OWNER,
            "vaultId": VAULT,
            "entries": [{"binding": self.binding, "state": "active"}],
        }
        self.head = live_projection(
            {**projection()[0], "sourcesDigest": source_index_digest(self.index["entries"])}
        )
        self.writer.heads.install(self.head, expected_version=0)
        self.write(SOURCE_INDEX, OWNER, self.index)
        self.write(HOLDINGS_FENCES, self.fence_key, self.fence)
        self.request = {
            "contractVersion": CONTRACT_VERSION,
            "ownerSubject": OWNER,
            "mutationId": "synthetic_old_source_mutation_01",
            "ref": self.ref,
            "expectedSourceEpoch": 2,
            "newSourceEpoch": 3,
            "reason": "deleted",
        }

    def read(self, table, key):
        with self.store.connection() as db:
            return self.store.value(db, table, key)

    def write(self, table, key, body):
        with self.store.connection() as db:
            db.execute(
                f"INSERT OR REPLACE INTO {table}(owner,value) VALUES (?, ?)",
                (key, canonical_json(body).decode()),
            )

    def report(self, revision=3):
        return ReportSourceAuthority(self.store).decide(
            UID,
            {
                "contractVersion": CONTRACT_VERSION,
                "profile": REPORT_PROFILE,
                "purpose": "report_submit",
                "ownerSubject": OWNER,
                "vaultId": VAULT,
                "connectionId": "connection_A",
                "runId": "run_A",
                "operationId": "synthetic_report_operation_0001",
                "attemptId": "synthetic_report_attempt_0001",
                "reportFingerprint": "a" * 64,
                "manifestFingerprint": "b" * 64,
                "resources": [{**self.binding, "sourceRevision": revision}],
            },
        )

    def test_revocation_updates_report_gate_recovery_digest_and_receipt_together(self):
        self.assertEqual(self.report()["outcome"], "allowed")
        receipt = self.writer.invalidate(self.request)
        self.assertEqual(self.report()["outcome"], "denied")
        self.assertEqual(receipt["acknowledgedSourceEpoch"], 3)
        self.assertEqual(self.writer.heads.read(OWNER)["sourcesDigest"], source_index_digest([]))
        self.assertEqual(self.read(HOLDINGS_FENCES, self.fence_key)["state"], "deleted")
        self.assertEqual(self.read(SOURCE_INDEX, OWNER)["entries"], [])
        self.now += 400
        self.assertEqual(self.writer.invalidate(self.request), receipt)
        with self.assertRaisesRegex(ContractError, "idempotency_conflict"):
            self.writer.invalidate({**self.request, "reason": "disconnected"})
        with self.assertRaisesRegex(ContractError, "version_conflict"):
            self.writer.invalidate(
                {
                    **self.request,
                    "mutationId": "synthetic_new_source_mutation_02",
                    "expectedSourceEpoch": 3,
                    "newSourceEpoch": 4,
                    "reason": "account_scope_changed",
                }
            )

    def test_current_portfolio_revision_advances_once_and_never_revives_a_retired_source(self):
        revision = PortfolioSourceRevision(
            contractVersion=CONTRACT_VERSION,
            ownerSubject=OWNER,
            vaultId=VAULT,
            ref=self.ref,
            sourceEpoch=2,
            sourceRevision=4,
        )
        self.assertEqual(self.report(4)["outcome"], "denied")
        first = self.writer.acknowledge_revision(revision)
        self.assertEqual(first, revision.model_dump())
        self.assertEqual(self.writer.acknowledge_revision(revision), first)
        self.assertEqual(
            self.writer.acknowledge_revision(revision.model_copy(update={"sourceRevision": 3})),
            first,
        )
        self.assertEqual(self.report(4)["outcome"], "allowed")
        self.assertEqual(self.writer.heads.read(OWNER), self.head)
        self.writer.invalidate(self.request)
        with self.assertRaisesRegex(ContractError, "version_conflict"):
            self.writer.acknowledge_revision(revision)
        self.assertEqual(self.report(4)["outcome"], "denied")
        self.assertEqual(self.read(HOLDINGS_FENCES, self.fence_key)["currentRevision"], 0)

    def test_shadow_or_foreign_incarnation_cannot_write_or_create_a_receipt(self):
        different = {**self.ref, "incarnation": "other_incarnation"}
        with self.assertRaisesRegex(ContractError, "version_conflict"):
            self.writer.invalidate({**self.request, "ref": different})
        shadow = {key: value for key, value in self.head.items() if key != "handover"}
        self.write(HEADS, OWNER, shadow)
        with self.assertRaisesRegex(ContractError, "source_unavailable"):
            self.writer.invalidate(self.request)
        self.assertIsNone(
            self.read(
                INVALIDATION_RECEIPTS, invalidation_receipt_key(OWNER, self.request["mutationId"])
            )
        )
        self.assertEqual(self.read(HOLDINGS_FENCES, self.fence_key), self.fence)

    def test_storage_failure_rolls_back_recovery_head_and_leaves_fence_unchanged(self):
        with self.store.connection() as db:
            db.execute(
                f"CREATE TRIGGER fail_ack BEFORE INSERT ON {INVALIDATION_RECEIPTS} "
                "BEGIN SELECT RAISE(ABORT, 'synthetic transaction failure'); END"
            )
        with self.assertRaisesRegex(ContractError, "authorization_unavailable"):
            self.writer.invalidate(self.request)
        self.assertEqual(self.writer.heads.read(OWNER), self.head)
        self.assertEqual(self.read(SOURCE_INDEX, OWNER), self.index)
        self.assertEqual(self.read(HOLDINGS_FENCES, self.fence_key), self.fence)

    def test_firestore_uses_one_transaction_for_authority_fence_index_and_receipt(self):
        operation = self.request["mutationId"]
        receipt = invalidation_receipt_key(OWNER, operation)
        rows = {
            f"{HEADS}/{OWNER}": {"view": canonical_json(self.head)},
            f"{SOURCE_INDEX}/{OWNER}": self.index,
            f"{HOLDINGS_FENCES}/{self.fence_key}": self.fence,
            f"{INVALIDATION_RECEIPTS}/{receipt}": None,
        }
        client, transaction = Mock(_database="user-data"), Mock()

        def reference(name, key):
            path = f"{name}/{key}"
            result = SimpleNamespace(_document_path=path)
            result.get = Mock(side_effect=lambda **kwargs: read(result, **kwargs))
            return result

        def read(ref, **kwargs):
            self.assertEqual(kwargs, {"transaction": transaction, "timeout": 4, "retry": None})
            self.assertFalse(transaction.set.called)
            self.assertFalse(transaction.create.called)
            row = rows[ref._document_path]
            return SimpleNamespace(reference=ref, exists=row is not None, to_dict=lambda: row)

        client.collection.side_effect = lambda name: SimpleNamespace(
            document=lambda key: reference(name, key)
        )
        client.get_all.side_effect = lambda references, **kwargs: [
            read(ref, **kwargs) for ref in reversed(references)
        ]
        with (
            patch("app.resources.firestore.Client", return_value=client),
            patch(
                "app.private_resources.source_invalidations.firestore.transactional", lambda fn: fn
            ),
            patch(
                "app.private_resources.source_invalidations.BoundedTransaction",
                return_value=transaction,
            ),
        ):
            store = FirestoreUserResourceStore("synthetic-project", "user-data")
            writer = SourceInvalidations(store, clock=lambda: self.now)
            with patch("app.private_resources.source_invalidations.erase_retired_names") as purge:
                ack = writer.invalidate(self.request)
                purge.assert_called_once_with(store, OWNER, self.ref)
            # Live replay conflicts retain their exact v2 errors across both stores.
            records = [call.args for call in transaction.set.call_args_list]
            created = transaction.create.call_args.args
            transaction.reset_mock()
            rows.update({ref._document_path: value for ref, value in [*records, created]})
            with self.assertRaisesRegex(ContractError, "idempotency_conflict"):
                writer.invalidate({**self.request, "reason": "disconnected"})
            transaction.set.assert_not_called()
            transaction.create.assert_not_called()
        self.assertEqual(ack["mutationId"], operation)
        sent = {ref._document_path: value for ref, value in records}
        self.assertEqual(
            set(sent),
            {f"{HEADS}/{OWNER}", f"{SOURCE_INDEX}/{OWNER}", f"{HOLDINGS_FENCES}/{self.fence_key}"},
        )
        self.assertEqual(sent[f"{SOURCE_INDEX}/{OWNER}"]["entries"], [])
        self.assertIn(source_index_digest([]).encode(), sent[f"{HEADS}/{OWNER}"]["view"])
        path, document = created
        self.assertEqual(path._document_path, f"{INVALIDATION_RECEIPTS}/{receipt}")
        self.assertEqual(document["ack"], ack)

    def test_route_is_off_by_default_and_accepts_only_portfolio_workload(self):
        headers = {
            "X-FolioView-Contract": CONTRACT_VERSION,
            "Authorization": "Bearer synthetic_portfolio",
        }
        verifier = Mock()
        with TestClient(app) as client:
            with patch.dict("os.environ", {"USER_PRIVATE_SOURCE_INVALIDATIONS": "false"}):
                self.assertEqual(
                    client.post(
                        PORTFOLIO_FENCE_PATH, json=self.request, headers=headers
                    ).status_code,
                    404,
                )
            with (
                patch.dict(app.dependency_overrides, {portfolio_invalidation: lambda: self.writer}),
                patch("app.private_resources.api.configured_owner_proxy", return_value=verifier),
            ):
                verifier.verify.side_effect = UntrustedServiceCaller
                denied = client.post(PORTFOLIO_FENCE_PATH, json=self.request, headers=headers)
                self.assertEqual(denied.status_code, 403, denied.text)
                self.assertEqual(self.read(HOLDINGS_FENCES, self.fence_key), self.fence)
                verifier.verify.side_effect = None
                no_scope = client.post(
                    PORTFOLIO_FENCE_PATH,
                    json=self.request,
                    headers={**headers, "X-FolioView-Delegation": "synthetic_untrusted"},
                )
                self.assertEqual(no_scope.status_code, 403, no_scope.text)
                accepted = client.post(PORTFOLIO_FENCE_PATH, json=self.request, headers=headers)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.headers["cache-control"], "no-store")
        self.assertEqual(accepted.json()["acknowledgedSourceEpoch"], 3)
