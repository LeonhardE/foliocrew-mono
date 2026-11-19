"""Additive private resource contracts with synthetic state and keys."""

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from test_encrypted_authority import AuthorityFixture

from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.private_resources import (
    RECOVERY_PROFILE,
    REPORT_PROFILE,
    PrivateRegistryCursor,
    _document,
    decide_report_sources,
    plan_history_watermark,
    recovery_request_digest,
    report_source_request,
    require_report_source_permit,
    source_index_digest,
    validate_history_reference,
    verify_owner_recovery_evidence,
    verify_private_registry_page,
    verify_private_registry_transition,
)

VECTOR = json.loads((Path(__file__).parent / "fixtures/private_resources.json").read_text())


class ReportSourceTests(unittest.TestCase):
    def setUp(self):
        self.request, self.snapshot = copy.deepcopy((VECTOR["request"], VECTOR["snapshot"]))

    def test_report_decision_is_bound_to_one_attempt_and_all_sources(self):
        decision = decide_report_sources(self.request, snapshot=self.snapshot, now=1000)
        self.assertEqual(decision, VECTOR["decision"])
        self.assertIsNone(require_report_source_permit(decision, request=self.request, now=1029))
        for field, value in {
            "attemptId": "other_report_attempt_0001",
            "operationId": "other_report_operation_0001",
            "reportFingerprint": "9" * 64,
            "manifestFingerprint": "8" * 64,
            "ownerSubject": "owner_other",
            "vaultId": "vault_other",
            "connectionId": "connection_other",
            "runId": "run_other",
        }.items():
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ContractError, "recipient_binding_mismatch"),
            ):
                require_report_source_permit(
                    decision, request={**self.request, field: value}, now=1001
                )
        self.request["resources"][0]["sourceRevision"] += 1
        with self.assertRaisesRegex(ContractError, "recipient_binding_mismatch"):
            require_report_source_permit(decision, request=self.request, now=1001)

    def test_revoke_after_allow_preserves_that_attempt_only(self):
        decision = decide_report_sources(self.request, snapshot=self.snapshot, now=1000)
        first = self.snapshot["resources"][0]
        first["binding"]["sourceEpoch"] += 1
        first["state"] = "deleted"
        later = {**self.request, "attemptId": "synthetic_report_attempt_0002"}
        denied = decide_report_sources(later, snapshot=self.snapshot, now=1001)
        self.assertEqual(denied["outcome"], "denied")
        require_report_source_permit(decision, request=self.request, now=1001)
        with self.assertRaisesRegex(ContractError, "insufficient_scope"):
            require_report_source_permit(denied, request=later, now=1001)
        with self.assertRaisesRegex(ContractError, "source_unavailable"):
            require_report_source_permit(decision, request=self.request, now=1030)

    def test_unknown_outcome_incomplete_snapshot_or_wrong_vault_fail_closed(self):
        with self.assertRaisesRegex(ContractError, "source_unavailable"):
            require_report_source_permit(None, request=self.request, now=1000)
        with self.assertRaisesRegex(ContractError, "source_unavailable"):
            decide_report_sources(self.request, snapshot=None, now=1000)
        with self.assertRaisesRegex(ContractError, "recipient_binding_mismatch"):
            decide_report_sources(
                self.request, snapshot={**self.snapshot, "vaultId": "other"}, now=1000
            )
        self.snapshot["resources"].pop()
        with self.assertRaisesRegex(ContractError, "source_unavailable"):
            decide_report_sources(self.request, snapshot=self.snapshot, now=1000)

    def test_replaced_incarnation_and_unobserved_revision_do_not_authorize(self):
        first = self.snapshot["resources"][0]
        first["currentRevision"] = 1
        self.assertEqual(
            decide_report_sources(self.request, snapshot=self.snapshot, now=1000)["outcome"],
            "denied",
        )
        first["currentRevision"] = 20
        first["binding"]["ref"]["incarnation"] = "incarnation_new"
        self.assertEqual(
            decide_report_sources(self.request, snapshot=self.snapshot, now=1000)["outcome"],
            "denied",
        )
        self.request["resources"].append(copy.deepcopy(self.request["resources"][0]))
        self.request["resources"][-1]["ref"]["incarnation"] = "other"
        with self.assertRaisesRegex(ContractError, "malformed_request"):
            report_source_request(self.request)


class RecoveryTests(unittest.TestCase):
    def test_fresh_evidence_binds_device_request_and_pins_monotonic_state(self):
        req = VECTOR["recovery"]
        value = VECTOR["evidence"]
        kwargs = {"request": req, "pinned_root_key_id": value["rootKeyId"], "now": 1020}
        self.assertEqual(recovery_request_digest(req), value["requestDigest"])
        self.assertEqual(verify_owner_recovery_evidence(value, **kwargs), value)
        with self.assertRaisesRegex(ContractError, "recipient_binding_mismatch"):
            verify_owner_recovery_evidence(
                value, **{**kwargs, "request": {**req, "deviceId": "other_device"}}
            )
        with self.assertRaisesRegex(ContractError, "key_authorization_required"):
            verify_owner_recovery_evidence({**value, "device": "inactive"}, **kwargs)
        with self.assertRaisesRegex(ContractError, "key_authorization_required"):
            verify_owner_recovery_evidence(
                {**value, "archive": {**value["archive"], "state": "deleted"}}, **kwargs
            )
        with self.assertRaisesRegex(ContractError, "authorization_unavailable"):
            verify_owner_recovery_evidence(value, **{**kwargs, "now": 1060})
        with self.assertRaisesRegex(ContractError, "rollback_detected"):
            verify_owner_recovery_evidence(
                value, **kwargs, previous={**value, "vaultVersion": value["vaultVersion"] + 1}
            )
        with self.assertRaisesRegex(ContractError, "registry_conflict"):
            verify_owner_recovery_evidence(
                {**value, "registry": {**value["registry"], "registryEpoch": 2}}, **kwargs
            )

    def test_source_digest_only_contains_live_index_entries(self):
        rows = VECTOR["index"]
        self.assertEqual(source_index_digest(rows), VECTOR["evidence"]["sourcesDigest"])
        self.assertEqual(source_index_digest(rows), source_index_digest(list(reversed(rows))))
        with self.assertRaisesRegex(ContractError, "malformed_request"):
            source_index_digest([{**rows[0], "state": "deleted"}])


class SegmentedRegistryTests(unittest.TestCase):
    def setUp(self):
        self.f = AuthorityFixture()
        self.scope = {
            "ownerSubject": self.f.owner,
            "vaultId": self.f.vault,
            "rootKeyId": self.f.root_id,
        }
        self.expect = {
            "root_jwk": self.f.root_public,
            "pinned_root_key_id": self.f.root_id,
            "owner_subject": self.f.owner,
            "vault_id": self.f.vault,
            "now": 1000,
        }

    def page(self, base, target, bundles):
        return {
            **self.scope,
            "contractVersion": CONTRACT_VERSION,
            "profile": "folioview.owner-registry-page.v1",
            "base": base.head() if base else None,
            "target": target,
            "bundles": bundles,
        }

    def test_contiguous_pages_cross_original_32_checkpoint_limit(self):
        bundles, end = [], None
        for _ in range(33):
            bundle = self.f.make_bundle(previous=end)
            end = self.f.verify(bundle, previous=end)
            bundles.append(bundle)
        target = PrivateRegistryCursor(end, 1).head()
        cursor = None
        for offset in range(0, 33, 5):
            page = self.page(cursor, target, bundles[offset : offset + 5])
            cursor = verify_private_registry_page(
                page, **self.expect, trusted_target=target, previous=cursor
            )
        self.assertEqual(cursor.head(), target)
        with self.assertRaisesRegex(ContractError, "registry_conflict"):
            verify_private_registry_page(
                self.page(None, target, bundles[1:2]),
                **self.expect,
                trusted_target=target,
                previous=None,
            )
        with self.assertRaisesRegex(ContractError, "registry_conflict"):
            verify_private_registry_page(
                self.page(None, target, bundles[:1]),
                **self.expect,
                trusted_target={**target, "checkpointDigest": "0" * 64},
                previous=None,
            )

    def test_same_root_transition_requires_current_epoch_anchor_and_owner_only_keys(self):
        prior = PrivateRegistryCursor(self.f.registry, 1)
        owner_certs = {
            key: cert for key, cert in self.f.certificates.items() if cert["connectionId"] is None
        }
        bundle = self.f.make_bundle(previous=prior.registry, certificates=owner_certs)
        start = PrivateRegistryCursor(self.f.verify(bundle), 2)
        payload = {
            **self.scope,
            "contractVersion": CONTRACT_VERSION,
            "profile": "folioview.owner-registry-transition.v1",
            "operationId": "synthetic_registry_start_0001",
            "previousVaultVersion": 30,
            "nextVaultVersion": 31,
            "previousHead": prior.head(),
            "nextHead": start.head(),
            "ownerKeyIds": sorted(start.registry.active_key_ids),
            "archive": VECTOR["evidence"]["archive"],
            "issuedAt": start.registry.issued_at,
        }
        signed = self.f.sign(payload, "root")
        kwargs = {**self.expect, "first_bundle": bundle, "authenticated_start": start.head()}
        cursor = verify_private_registry_transition(signed, **kwargs, previous=prior)
        self.assertEqual(cursor.head(), start.head())
        self.assertEqual(verify_private_registry_transition(signed, **kwargs).head(), start.head())
        with self.assertRaisesRegex(ContractError, "rollback_detected"):
            verify_private_registry_transition(
                signed, **{**kwargs, "authenticated_start": prior.head()}
            )
        with self.assertRaisesRegex(ContractError, "rollback_detected"):
            verify_private_registry_page(
                self.page(prior, start.head(), [bundle]),
                **self.expect,
                trusted_target=start.head(),
                previous=prior,
            )
        with self.assertRaisesRegex(ContractError, "key_authorization_required"):
            cursor.registry.cert(self.f.kid("A1_sig"), now=1000)
        foreign_bundle = self.f.make_bundle(previous=prior.registry)
        wrong_start = PrivateRegistryCursor(self.f.verify(foreign_bundle), 2)
        wrong_payload = {
            **payload,
            "nextHead": wrong_start.head(),
            "ownerKeyIds": sorted(wrong_start.registry.active_key_ids),
        }
        with self.assertRaisesRegex(ContractError, "key_authorization_required"):
            verify_private_registry_transition(
                self.f.sign(wrong_payload, "root"),
                **self.expect,
                first_bundle=foreign_bundle,
                authenticated_start=wrong_start.head(),
            )


class HistoryReferenceTests(unittest.TestCase):
    def test_reclaim_is_bounded_by_live_pins_and_late_pins_use_current_watermark(self):
        watermark = {
            **{key: VECTOR["evidence"][key] for key in ("ownerSubject", "vaultId", "rootKeyId")},
            "generation": 1,
            "registryEpoch": 1,
            "committedThroughSequence": 0,
        }
        pin = {
            **{
                key: value
                for key, value in watermark.items()
                if key not in {"generation", "committedThroughSequence"}
            },
            "contractVersion": CONTRACT_VERSION,
            "profile": "folioview.private-history-reference.v1",
            "holderId": "agent_hub",
            "referenceId": "report_A",
            "purpose": "report",
            "firstSequence": 18,
            "lastSequence": 21,
        }
        next_floor = plan_history_watermark(watermark, retired_through=27, references=[pin])
        self.assertEqual(next_floor["committedThroughSequence"], 17)
        self.assertEqual(next_floor["generation"], 2)
        self.assertEqual(validate_history_reference(pin, watermark=next_floor), pin)
        released = plan_history_watermark(next_floor, retired_through=27, references=[])
        with self.assertRaisesRegex(ContractError, "version_conflict"):
            validate_history_reference(pin, watermark=released)

    def test_contracts_are_additive_closed_and_use_expected_profiles(self):
        Draft202012Validator.check_schema(_document())
        self.assertEqual(VECTOR["request"]["profile"], REPORT_PROFILE)
        self.assertEqual(VECTOR["recovery"]["profile"], RECOVERY_PROFILE)
