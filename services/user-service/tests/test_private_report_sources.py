"""User decisions are atomically bound to current private sources."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from test_private_recovery import OWNER, UID, VAULT, projection

from app.main import app
from app.private_resources.api import REPORT_DECISION_PATH, report_authority, report_verifier
from app.private_resources.recovery import COLLECTION, RecoveryHeads, current_recovery_evidence
from app.private_resources.report_sources import (
    HOLDINGS_FENCES,
    ReportSourceAuthority,
    holdings_fence_key,
)
from app.resource_versions import version_key
from app.resources import COLLECTIONS, FirestoreUserResourceStore, SQLiteUserResourceStore
from app.watchlist import SQLiteWatchlistStore
from folioview_shared.delegation import DelegationError
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json
from folioview_shared.encrypted.private_resources import (
    REPORT_PROFILE,
    require_report_source_permit,
)


def live_projection(head):
    return {
        **head,
        "handover": {
            "operationId": "synthetic_handover_operation_0001",
            "baselineDigest": "c" * 64,
            "writerEpoch": 1,
        },
    }


class ReportSourceTests(unittest.TestCase):
    def setUp(self):
        local = tempfile.TemporaryDirectory()
        self.addCleanup(local.cleanup)
        store = SQLiteUserResourceStore(str(Path(local.name) / "user.sqlite3"))
        self.authority = ReportSourceAuthority(store)
        self.head, self.recovery_request = projection()
        RecoveryHeads(store).install(live_projection(self.head), expected_version=0)
        SQLiteWatchlistStore(store.path).change(
            UID,
            "AAPL",
            {
                "symbol": "AAPL",
                "name": "Synthetic Apple",
                "instrumentType": "stock",
                "currency": "USD",
                "addedAt": "2026-11-19T01:00:00.000000Z",
            },
        )
        current = store.read(UID, ("watchlist",))["watchlist"]
        self.holdings = {
            "ref": {
                "kind": "holdings",
                "sourceService": "portfolio",
                "resourceId": "holdings_synthetic",
                "incarnation": "incarnation_initial",
            },
            "sourceEpoch": 3,
        }
        self.request = {
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
            "resources": [
                {**self.holdings, "sourceRevision": 2},
                {
                    "ref": current["ref"],
                    "sourceEpoch": current["sourceEpoch"],
                    "sourceRevision": current["revision"],
                },
            ],
        }

    def change_fence(self, *, state="eligible", binding=None):
        with self.authority.store.connection() as db:
            db.execute(
                f"INSERT OR REPLACE INTO {HOLDINGS_FENCES}(owner, value) VALUES (?, ?)",
                (
                    holdings_fence_key(OWNER, VAULT, self.holdings["ref"]["resourceId"]),
                    json.dumps(
                        {
                            "ownerSubject": OWNER,
                            "vaultId": VAULT,
                            "state": state,
                            "binding": binding or self.holdings,
                            "currentRevision": 3,
                        }
                    ),
                ),
            )

    def test_revocation_order_and_replacement_are_seen_on_each_attempt(self):
        self.assertEqual(self.authority.decide(UID, self.request)["outcome"], "denied")
        self.change_fence()
        with patch("app.private_resources.report_sources.time.time", return_value=1000):
            accepted = self.authority.decide(UID, self.request)
        self.assertEqual(accepted["outcome"], "allowed")
        self.change_fence(state="revoking")
        later = {**self.request, "attemptId": "synthetic_report_attempt_0002"}
        self.assertEqual(self.authority.decide(UID, later)["outcome"], "denied")
        require_report_source_permit(accepted, request=self.request, now=1001)
        with self.assertRaisesRegex(ContractError, "recipient_binding_mismatch"):
            require_report_source_permit(accepted, request=later, now=1001)
        self.change_fence(
            binding={
                "ref": {**self.holdings["ref"], "incarnation": "incarnation_replaced"},
                "sourceEpoch": 4,
            }
        )
        self.assertEqual(self.authority.decide(UID, later)["outcome"], "denied")

    def test_shadow_head_cannot_authorize_a_report_or_promote_by_ordinary_install(self):
        self.change_fence()
        store = self.authority.store
        heads = RecoveryHeads(store)
        evidence = current_recovery_evidence(heads, UID, VAULT, self.recovery_request, 1000)
        self.assertNotIn("handover", evidence)
        shadow = self.head
        with store.connection() as db:
            db.execute(
                f"UPDATE {COLLECTION} SET value=? WHERE owner=?",
                (canonical_json(shadow).decode(), OWNER),
            )
        with self.assertRaisesRegex(ContractError, "source_unavailable"):
            self.authority.decide(UID, self.request)
        with self.assertRaisesRegex(ContractError, "version_conflict"):
            RecoveryHeads(store).install(
                {**live_projection(shadow), "vaultVersion": shadow["vaultVersion"] + 1},
                expected_version=shadow["vaultVersion"],
            )
        self.assertIsNone(RecoveryHeads(store).read(OWNER).get("handover"))

    def test_coverage_cross_owner_and_failed_reads_never_permit(self):
        self.change_fence()
        for uid, request in (
            ("another-account", self.request),
            (UID, {**self.request, "vaultId": "another_vault"}),
        ):
            with self.subTest(uid=uid), self.assertRaisesRegex(ContractError, "insufficient_scope"):
                self.authority.decide(uid, request)
        with (
            patch.object(self.authority, "_read", side_effect=RuntimeError),
            self.assertRaisesRegex(ContractError, "source_unavailable"),
        ):
            self.authority.decide(UID, self.request)

    def test_firestore_reads_the_fence_and_current_list_in_one_bounded_batch(self):
        self.change_fence()
        key = holdings_fence_key(OWNER, VAULT, self.holdings["ref"]["resourceId"])
        with self.authority.store.connection() as db:
            content, metadata = self.authority.store.pair(db, UID, "watchlist")
            rows = {
                f"{COLLECTION}/{OWNER}": {"view": canonical_json(live_projection(self.head))},
                f"{COLLECTIONS['watchlist']}/{OWNER}": content,
                f"user_resource_versions/{version_key(UID, 'watchlist')}": metadata,
                f"{HOLDINGS_FENCES}/{key}": self.authority.store.value(db, HOLDINGS_FENCES, key),
            }

        def collection(name):
            return SimpleNamespace(
                document=lambda key: SimpleNamespace(_document_path=f"{name}/{key}")
            )

        def get_all(references, **kwargs):
            self.assertEqual(kwargs, {"transaction": transaction, "timeout": 4, "retry": None})
            self.assertEqual({ref._document_path for ref in references}, rows.keys())
            return [
                SimpleNamespace(
                    reference=ref, exists=True, to_dict=lambda ref=ref: rows[ref._document_path]
                )
                for ref in reversed(references)
            ]

        transaction = MagicMock()
        client = MagicMock()
        client.collection.side_effect = collection
        client.get_all.side_effect = get_all
        with (
            patch("app.resources.firestore.Client", return_value=client),
            patch("app.private_resources.report_sources.firestore.transactional", lambda fn: fn),
            patch(
                "app.private_resources.report_sources.BoundedTransaction", return_value=transaction
            ),
        ):
            store = FirestoreUserResourceStore("synthetic-project", "user-data")
            result = ReportSourceAuthority(store).decide(UID, self.request)
        self.assertEqual(result["outcome"], "allowed")
        client.get_all.assert_called_once()
        transaction.set.assert_not_called()

    def test_route_has_a_separate_enablement_and_requires_both_credentials(self):
        self.change_fence()
        verifier = MagicMock()
        verifier.verify_report_attempt.return_value = UID
        headers = {
            "X-FolioView-Contract": CONTRACT_VERSION,
            "Authorization": "Bearer synthetic-workload",
            "X-FolioView-Delegation": "synthetic-delegation",
        }
        with TestClient(app) as client:
            with patch.dict("os.environ", {"USER_REPORT_SOURCE_DECISIONS": "false"}):
                response = client.post(REPORT_DECISION_PATH, json=self.request, headers=headers)
            self.assertEqual(response.status_code, 404)
            with patch.dict(
                app.dependency_overrides,
                {
                    report_authority: lambda: self.authority,
                    report_verifier: lambda: verifier,
                },
            ):
                incomplete = {k: v for k, v in headers.items() if k != "X-FolioView-Delegation"}
                self.assertEqual(
                    client.post(
                        REPORT_DECISION_PATH, json=self.request, headers=incomplete
                    ).status_code,
                    401,
                )
                verifier.verify_report_attempt.assert_not_called()
                outcome = client.post(REPORT_DECISION_PATH, json=self.request, headers=headers)
                self.assertEqual(outcome.status_code, 200)
                self.assertEqual(outcome.headers["cache-control"], "no-store")
                self.assertEqual(outcome.json()["outcome"], "allowed")
                verifier.verify_report_attempt.assert_called_once_with(
                    "synthetic-workload", "synthetic-delegation", request=self.request
                )
                verifier.verify_report_attempt.side_effect = DelegationError("permission_denied")
                self.assertEqual(
                    client.post(
                        REPORT_DECISION_PATH, json=self.request, headers=headers
                    ).status_code,
                    403,
                )
