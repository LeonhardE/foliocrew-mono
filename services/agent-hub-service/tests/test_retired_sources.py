"""Verified User receipts stop migrated Hub artifacts being stranded or resurrected."""

import copy
import os
import unittest
import uuid

import test_user_vault_authority as authority_fixture
from test_fences import OWNER, REF, mutation

from app.fences import FenceService, _fingerprint, fence_path
from app.repair_retired_sources import repair
from app.source_erasure import process_sources
from app.store import StoreUnavailable, private_resource_writer_fence_path
from folioview_shared.encrypted.crypto import _signed_parts
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json


class RetiredSourcesTests(unittest.TestCase):
    def setUp(self):
        fx = authority_fixture.UserVaultAuthorityTests()
        fx.setUp()
        self.addCleanup(fx.doCleanups)
        self.fx = fx
        self.store = fx.store
        self.marker_path = private_resource_writer_fence_path(OWNER)
        self.set_writer(fx.fence)
        a = fx.authority
        self.vault = a["vaultId"]
        start, signed = a["registryStart"], a["signedTransition"]
        first = _signed_parts(signed)[1]
        self.head = {k: a[k] for k in ("ownerSubject", "vaultId", "rootKeyId", "vaultVersion")}
        self.head["handover"] = {
            "operationId": first["operationId"],
            "writerEpoch": 2,
            "baselineDigest": "d" * 64,
        }
        transfer_state = {
            k: a[k] for k in ("ownerSubject", "vaultId", "rootKeyId", "registryStart")
        }
        transfer = {
            "receipt": {
                **transfer_state,
                **self.head["handover"],
                "nextVaultVersion": first["nextVaultVersion"],
                "transitionFingerprint": fx.fence["transitionFingerprint"],
            },
            "signedTransition": signed,
        }
        self.request = mutation(7, reason="deleted")
        self.ref_key = _fingerprint([OWNER, self.vault, REF["resourceId"]])
        self.key = _fingerprint([OWNER, "portfolio", self.request["mutationId"]])
        self.rows = {
            ("user_private_recovery_heads", OWNER): {"view": canonical_json(self.head)},
            ("user_private_handover_receipts", OWNER): {"record": canonical_json(transfer)},
            (
                "user_private_registry_history",
                _fingerprint(
                    [OWNER, self.vault, start["registryEpoch"], start["registrySequence"]]
                ),
            ): {
                "entry": canonical_json(
                    {"head": start, "bundle": a["registryHistory"][0], "rootJwk": a["rootJwk"]}
                )
            },
            ("user_private_holdings_fences", self.ref_key): {
                "ownerSubject": OWNER,
                "vaultId": self.vault,
                "state": "deleted",
                "currentRevision": 0,
                "binding": {"ref": copy.deepcopy(REF), "sourceEpoch": 8},
            },
        }
        self.receipt = {
            "ownerSubject": OWNER,
            "vaultId": self.vault,
            "request": self.request,
            "fingerprint": _fingerprint(self.request),
            "ack": {
                "contractVersion": self.request["contractVersion"],
                "mutationId": self.request["mutationId"],
                "ref": REF,
                "acknowledgedSourceEpoch": 8,
                "acknowledgedAt": "1970-01-01T00:16:40Z",
            },
        }
        self.service = FenceService(self.store, clock=lambda: 1001)

    def set_writer(self, writer):
        self.store.transact(lambda u: u.put(self.marker_path, writer))

    def run_repair(self, apply):
        return repair(
            self.store,
            OWNER,
            lambda t, k: self.rows[t, k],
            [(self.key, self.receipt)],
            apply=apply,
            clock=lambda: 1001,
        )

    def test_signed_transfer_and_exact_deleted_incarnation_allow_physical_cleanup_and_replay(self):
        self.assertEqual(
            self.run_repair(False), {"matched": 1, "completed": 0, "reviewRequired": 0}
        )
        self.assertIsNone(self.store.transact(lambda u: u.get(fence_path(OWNER, REF))))
        self.assertEqual(self.run_repair(True), {"matched": 1, "completed": 1, "reviewRequired": 0})
        ack = self.service.invalidate(self.request, source_service="portfolio")
        self.assertEqual(ack["acknowledgedSourceEpoch"], 8)
        self.assertEqual(
            ack,
            FenceService(self.store, clock=lambda: 2000).invalidate(
                self.request, source_service="portfolio"
            ),
        )
        self.assertEqual(self.run_repair(True)["completed"], 1)
        with self.assertRaises(ContractError):
            self.service.invalidate(mutation(8), source_service="portfolio")

    def test_frozen_cutover_defers_the_sweeper_and_mirror(self):
        self.set_writer({**self.fx.fence, "state": "frozen"})
        with self.assertRaises(ContractError):
            self.service.invalidate(self.request, source_service="portfolio")
        self.set_writer(self.fx.fence)
        self.service.invalidate(self.request, source_service="portfolio")
        self.set_writer({**self.fx.fence, "state": "frozen"})
        self.assertEqual(
            process_sources(self.store, apply=True),
            {"eligible": 1, "completed": 0, "deferred": 1, "failed": 0},
        )
        self.set_writer(self.fx.fence)
        self.assertEqual(process_sources(self.store, apply=True)["completed"], 1)

    def test_replaced_incarnation_or_conflicting_receipt_never_authorizes_erasure(self):
        self.rows["user_private_holdings_fences", self.ref_key]["binding"]["ref"]["incarnation"] = (
            "another_incarnation"
        )
        self.assertEqual(self.run_repair(True)["reviewRequired"], 1)
        self.assertIsNone(self.store.transact(lambda u: u.get(fence_path(OWNER, REF))))
        self.rows["user_private_holdings_fences", self.ref_key]["binding"]["ref"] = REF
        self.receipt["fingerprint"] = "b" * 64
        self.assertEqual(self.run_repair(True)["reviewRequired"], 1)
        self.assertIsNone(self.store.transact(lambda u: u.get(fence_path(OWNER, REF))))

    def test_wrong_transfer_or_changed_writer_refuses_entire_repair(self):
        self.set_writer({**self.fx.fence, "transitionFingerprint": "b" * 64})
        with self.assertRaises(StoreUnavailable):
            self.run_repair(True)
        with self.assertRaises(ContractError):
            self.service.invalidate(
                self.request, source_service="portfolio", expected_writer=self.fx.fence
            )
        self.assertIsNone(self.store.transact(lambda u: u.get(fence_path(OWNER, REF))))

    @unittest.skipUnless(
        os.getenv("FIRESTORE_EMULATOR_HOST", "").startswith("127.0.0.1:"), "loopback emulator"
    )
    def test_named_user_and_hub_databases_remove_only_the_authorized_copy(self):
        from google.auth.credentials import AnonymousCredentials
        from google.cloud import firestore

        from app.private_display_names import name_path
        from app.store import FirestoreHubStore

        project = "demo-src-erase-" + uuid.uuid4().hex[:9]
        hub, user = (
            firestore.Client(project=project, database=n, credentials=AnonymousCredentials())
            for n in ("agent-hub", "user-data")
        )
        self.addCleanup(user.close)
        self.addCleanup(hub.close)
        self.store = FirestoreHubStore(project, "agent-hub", client=hub)
        self.set_writer(self.fx.fence)
        for (table, key), row in self.rows.items():
            user.collection(table).document(key).set(row)
        receipts = user.collection("user_private_source_invalidation_receipts")
        receipts.document(self.key).set(self.receipt)
        target, other = [
            name_path(OWNER, self.vault, self.fx.fence["rootKeyId"], r)
            for r in (REF, {**REF, "incarnation": "another_incarnation"})
        ]
        for path, ref in ((target, REF), (other, {**REF, "incarnation": "another_incarnation"})):
            hub.document(path).set(
                {
                    "state": {
                        "ownerSubject": OWNER,
                        "rootKeyId": self.fx.fence["rootKeyId"],
                        "vaultId": self.vault,
                        "ref": ref,
                        "encryptedName": "synthetic-ciphertext",
                    }
                }
            )
        counts = repair(
            self.store,
            OWNER,
            lambda t, k: user.collection(t).document(k).get().to_dict(),
            ((r.id, r.to_dict()) for r in receipts.stream()),
            apply=True,
            clock=lambda: 1001,
        )
        self.assertEqual(counts, {"matched": 1, "completed": 1, "reviewRequired": 0})
        self.assertFalse(hub.document(target).get().exists)
        self.assertTrue(hub.document(other).get().exists)
