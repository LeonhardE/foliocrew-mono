"""Current result writes and historical owner reads are separate trust decisions."""

import copy
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

import test_persistent_execution as executions
from fixtures import OTHER_UID, UID
from test_persistent_content import PersistentContentFixture

from app.fences import FenceService
from app.persistent_results import (
    PersistentOwnerResultService,
    PersistentResultService,
    result_id,
    result_path,
)
from app.store import private_resource_writer_fence_path
from folioview_shared.encrypted.crypto import _signed_parts, sign_jws, signing_input_fingerprint
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json
from folioview_shared.encrypted.persistent_content import (
    open_persistent_content,
    seal_persistent_content,
)
from folioview_shared.encrypted.private_resources import (
    REPORT_PERMIT_SECONDS,
    PrivateRegistryCursor,
    decide_report_sources,
)


class PersistentResultTests(unittest.TestCase):
    def setUp(self):
        self.x = executions.PersistentExecutionTests()
        self.x.setUp()
        self.addCleanup(self.x.doCleanups)
        self.f, self.fx, self.p = self.x.f, self.x.fx, self.x.p
        self.service = PersistentResultService(
            self.fx.store,
            self.fx.catalogue,
            audience=executions.ISSUER,
            client_ids=self.x.service.client_ids,
            clock=lambda: self.fx.now,
        )
        self.history = PersistentOwnerResultService(self.fx.store, clock=lambda: self.fx.now)
        self.run = self.x.begin()
        self.manifest = self.run["manifest"]
        self.operation = "synthetic_persistent_result_operation_0001"
        self.context = self.output_context()
        self.carrier = self.seal(self.context)

    def output_context(self, **changes):
        c = PersistentContentFixture.content_context(self.f, "result_revision")
        c.update(
            registrySequence=self.f.registry.registry_sequence,
            checkpointDigest=self.f.registry.checkpoint_digest,
            stableOperationId=self.operation,
            objectId=result_id(self.f.owner, self.f.vault, self.manifest["runId"]),
            **{
                k: self.manifest[k]
                for k in (
                    "taskId",
                    "taskVersion",
                    "executionEpoch",
                    "authorityId",
                    "authorityVersion",
                    "runId",
                )
            },
            manifestFingerprint=self.run["manifestFingerprint"],
        )
        return c | changes

    def seal(self, c):
        return seal_persistent_content(
            PersistentContentFixture.private_content(self.f, c),
            PersistentContentFixture.public_keys(self.f, c),
            context=c,
            signing_private_key=self.f.keys["A1_sig"],
        )

    def submit(self, *, carrier=None, operation=None):
        request = {
            "runId": self.manifest["runId"],
            "operationId": operation or self.operation,
            "envelope": carrier or self.carrier,
        }
        return self.service.submit(*self.x.args("runs/submit", request))

    def rejects(self, code, action):
        self.fx.rejects(code, action)

    def state_command(self, operation, expected, *, registry=None, **parameters):
        registry = self.f.registry if registry is None else registry
        return self.f.sign(
            {
                **self.f.base("control_command"),
                "stableOperationId": operation,
                "action": "result_state_update",
                "targetId": self.context["objectId"],
                "expectedVersion": expected,
                "expectedSourceEpoch": None,
                "registrySequence": registry.registry_sequence,
                "checkpointDigest": registry.checkpoint_digest,
                "keyEpoch": registry.key_epoch,
                "parameters": parameters,
            }
        )

    def test_save_is_atomic_and_both_owner_keys_open_original_report(self):
        receipt = self.submit()
        self.assertEqual(receipt["manifestFingerprint"], self.run["manifestFingerprint"])
        saved = self.history.owner_get(UID, self.f.vault, receipt["resultId"])
        self.assertEqual(saved["envelope"], self.carrier)
        self.assertEqual(saved["manifest"], self.manifest)
        for key in ("device_enc", "recovery_enc"):
            plain = open_persistent_content(
                saved["envelope"]["jwe"], self.f.keys[key], context=self.context
            )
            self.assertEqual(plain["payload"]["title"], "Synthetic daily report")
        self.assertNotIn("Synthetic", canonical_json(saved).decode())
        self.assertEqual(
            self.x.service.run_receipt(
                *self.x.args("runs/receipt", {"runId": self.manifest["runId"]})
            )["state"],
            "submitted",
        )

    def test_original_unknown_outcome_survives_source_outage_and_expired_run(self):
        receipt = self.submit()
        self.fx.now += 7300
        self.fx.catalogue.unavailable = True
        self.assertEqual(self.submit(), receipt)
        self.assertEqual(
            self.service.result_receipt(
                *self.x.args("runs/result-receipt", {"runId": self.manifest["runId"]})
            ),
            receipt,
        )
        self.rejects("idempotency_conflict", lambda: self.submit(carrier=self.seal(self.context)))

    def use_report_authority(self, *, eligible=True, after_decision=None):
        def decide(uid, request):
            self.assertEqual(uid, UID)
            decision = decide_report_sources(
                request,
                snapshot={
                    "ownerSubject": self.f.owner,
                    "vaultId": self.f.vault,
                    "resources": [
                        {
                            "binding": {
                                "ref": item["ref"],
                                "sourceEpoch": item["sourceEpoch"] + int(not eligible),
                            },
                            "state": "eligible" if eligible else "disconnected",
                            "currentRevision": item["sourceRevision"],
                        }
                        for item in request["resources"]
                    ],
                },
                now=self.fx.now,
            )
            if after_decision is not None:
                after_decision(request)
            return decision

        self.service.report_source_authority = Mock()
        self.service.report_source_authority.decide.side_effect = decide
        self.fx.catalogue.unavailable = True
        return self.service.report_source_authority.decide

    def set_migration_fence(self, state):
        path = private_resource_writer_fence_path(self.f.owner)
        row = {
            "ownerSubject": self.f.owner,
            "vaultId": self.f.vault,
            "state": state,
            "writerEpoch": 2,
        }
        self.fx.store.transact(lambda unit: unit.put(path, row))

    def test_user_authority_is_only_used_for_a_scoped_transferred_writer(self):
        decide = self.use_report_authority()
        self.service.selected_report_owner = self.f.owner
        self.rejects("source_unavailable", self.submit)
        self.set_migration_fence("frozen")
        self.rejects("source_unavailable", self.submit)
        decide.assert_not_called()
        self.assertIsNone(
            self.fx.store.transact(
                lambda unit: self.service._source_writer(unit, "b" * 64, self.f.vault)
            )
        )
        self.set_migration_fence("transferred")
        receipt = self.submit()
        self.assertEqual(self.submit(), receipt)
        decide.assert_called_once()

    def test_transferred_report_uses_current_user_proof_and_exact_decision(self):
        self.service.user_vaults = self.x.transferred_scope()
        self.service.selected_report_owner = self.f.owner
        decide = self.use_report_authority()
        with patch("app.persistent_agents._current", side_effect=AssertionError("legacy registry")):
            receipt = self.submit()
            self.assertEqual(self.submit(), receipt)
            decide.assert_called_once()
            self.assertEqual(
                self.service.result_receipt(
                    *self.x.args("runs/result-receipt", {"runId": self.manifest["runId"]})
                ),
                receipt,
            )

    def publish_after_transfer(self, *, advance_during_run):
        scopes = self.x.transferred_scope()
        self.x.service.user_vaults = self.service.user_vaults = scopes
        self.service.selected_report_owner = self.f.owner

        previous = self.f.registry
        first = self.f.make_bundle(previous=previous, issued_at=self.fx.now)
        start = self.f.verify(first, previous=previous, now=self.fx.now)
        scope = scopes.client.read.return_value
        scope.authority.update(
            registryStart=PrivateRegistryCursor(start, 2).head(), registryHistory=[first]
        )
        scopes.client.read.return_value = replace(scope, cursor=PrivateRegistryCursor(start, 2))
        self.run = self.x.begin(
            triggerId="synthetic_transferred_trigger_01",
            operationId="synthetic_transferred_begin_0001",
        )
        self.manifest = self.run["manifest"]
        issuance = start
        if advance_during_run:
            next_bundle = self.f.make_bundle(previous=start, issued_at=self.fx.now)
            issuance = self.f.verify(next_bundle, previous=start, now=self.fx.now)
            scope.authority["registryHistory"] = [first, next_bundle]
            scopes.client.read.return_value = replace(
                scope, cursor=PrivateRegistryCursor(issuance, 2)
            )
        self.context = self.output_context(
            registrySequence=issuance.registry_sequence,
            checkpointDigest=issuance.checkpoint_digest,
        )
        self.carrier = self.seal(self.context)
        self.use_report_authority()
        receipt = self.submit()
        scopes.client.read.reset_mock()
        return scopes, receipt

    def test_owner_read_uses_issuance_history_from_the_transferred_run(self):
        scopes, receipt = self.publish_after_transfer(advance_during_run=False)
        scopes.client.read.side_effect = ContractError("source_unavailable")
        saved = self.history.owner_get(UID, self.f.vault, receipt["resultId"])
        scopes.client.read.assert_not_called()
        self.assertEqual(
            saved["registryHistory"], scopes.client.read.return_value.authority["registryHistory"]
        )
        self.assertEqual(saved["receipt"], receipt)
        self.assertEqual(saved["envelope"], self.carrier)

    def test_owner_read_resolves_user_issuance_after_the_run_checkpoint(self):
        scopes, receipt = self.publish_after_transfer(advance_during_run=True)
        self.history = PersistentOwnerResultService(
            self.fx.store, clock=lambda: self.fx.now, user_vaults=scopes
        )
        saved = self.history.owner_get(UID, self.f.vault, receipt["resultId"])
        scope = scopes.client.read.return_value
        scopes.client.read.assert_called_once_with(UID, self.f.vault, scope.writer_fence)
        self.assertEqual(saved["registryHistory"], scope.authority["registryHistory"])
        self.assertEqual(saved["receipt"], receipt)
        self.assertEqual(saved["envelope"], self.carrier)

        self.fx.now = scope.expires_at
        self.rejects(
            "source_unavailable",
            lambda: self.history.owner_get(UID, self.f.vault, receipt["resultId"]),
        )

    def test_opening_a_transferred_report_can_mark_it_read(self):
        scopes, receipt = self.publish_after_transfer(advance_during_run=False)
        self.history = PersistentOwnerResultService(
            self.fx.store, clock=lambda: self.fx.now, user_vaults=scopes
        )
        result = receipt["resultId"]
        op = "synthetic_transferred_mark_read_01"
        args = (UID, self.f.vault, result)
        author = self.f.kid("device_sig")
        old = self.state_command(op, 0, read=True)
        self.rejects("rollback_detected", lambda: self.history.owner_state(*args, old, op, author))
        registry = scopes.client.read.return_value.cursor.registry
        current = self.state_command(op, 0, registry=registry, read=True)
        marked = self.history.owner_state(*args, current, op, author)
        self.assertTrue(marked["read"])
        self.assertEqual(marked["stateVersion"], 1)
        self.assertEqual(self.history.owner_state(*args, current, op, author), marked)

    def test_known_receipt_survives_legacy_freeze(self):
        receipt = self.submit()
        self.set_migration_fence("frozen")
        self.fx.catalogue.unavailable = True
        self.assertEqual(self.submit(), receipt)

    def test_frozen_writer_during_source_read_blocks_late_legacy_submit(self):
        from app.persistent_results import source_versions

        def source_then_freeze(catalogue, uid):
            observed = source_versions(catalogue, uid)
            self.set_migration_fence("frozen")
            return observed

        with patch("app.persistent_results.source_versions", side_effect=source_then_freeze):
            self.rejects("source_unavailable", self.submit)
        self.assertEqual(self.history.owner_list(UID, self.f.vault)["items"], [])
        self.assertEqual(
            self.x.service.run_receipt(
                *self.x.args("runs/receipt", {"runId": self.manifest["runId"]})
            )["state"],
            "ready",
        )

    def test_source_revocation_after_the_allowed_attempt_keeps_one_exact_receipt(self):
        def invalidate(request):
            first = request["resources"][0]
            FenceService(self.fx.store, clock=lambda: self.fx.now).invalidate(
                {
                    "contractVersion": request["contractVersion"],
                    "ownerSubject": self.f.owner,
                    "mutationId": "synthetic_source_fence_change_01",
                    "ref": first["ref"],
                    "expectedSourceEpoch": first["sourceEpoch"],
                    "newSourceEpoch": first["sourceEpoch"] + 1,
                    "reason": "disconnected",
                },
                source_service=first["ref"]["sourceService"],
            )

        choose = self.use_report_authority(after_decision=invalidate)
        receipt = self.submit()
        self.assertEqual(receipt, self.submit())
        self.assertEqual(len(self.history.owner_list(UID, self.f.vault)["items"]), 1)
        choose.assert_called_once()
        _, request = choose.call_args.args
        self.assertEqual(request["manifestFingerprint"], self.run["manifestFingerprint"])
        self.assertEqual(
            request["reportFingerprint"], signing_input_fingerprint(self.carrier["proof"])
        )
        self.assertEqual(request["operationId"], self.operation)
        self.assertNotEqual(request["operationId"], request["attemptId"])

    def test_denied_source_attempt_does_not_write_and_each_retry_has_a_fresh_binding(self):
        choose = self.use_report_authority(eligible=False)
        for _ in range(2):
            self.rejects("insufficient_scope", lambda: self.submit())
        self.assertEqual(self.history.owner_list(UID, self.f.vault)["items"], [])
        calls = [c.args[1] for c in choose.call_args_list]
        self.assertNotEqual(calls[0]["attemptId"], calls[1]["attemptId"])
        self.assertEqual(calls[0] | {"attemptId": None}, calls[1] | {"attemptId": None})
        self.rejects(
            "not_found",
            lambda: self.service.result_receipt(
                *self.x.args("runs/result-receipt", {"runId": self.manifest["runId"]})
            ),
        )

    def test_source_allow_still_checks_consent_before_commit(self):
        choose = self.use_report_authority(
            after_decision=lambda _: self.fx.apply(
                self.fx.command(targets=[self.fx.revoke_target()]), revoke=True
            )
        )
        self.rejects("insufficient_scope", lambda: self.submit())
        choose.assert_called_once()
        self.assertEqual(self.history.owner_list(UID, self.f.vault)["items"], [])

    def test_expired_or_mismatched_source_approval_never_writes(self):
        choose = self.use_report_authority()
        append = self.service._append

        def expire(*args):
            append(*args)
            self.fx.now += REPORT_PERMIT_SECONDS

        with patch.object(self.service, "_append", side_effect=expire):
            self.rejects("source_unavailable", lambda: self.submit())
        self.assertEqual(self.history.owner_list(UID, self.f.vault)["items"], [])
        prior = choose.call_args.args[1]
        choose.side_effect = None
        choose.return_value = decide_report_sources(
            prior,
            snapshot={
                "ownerSubject": self.f.owner,
                "vaultId": self.f.vault,
                "resources": [
                    {
                        "binding": {"ref": item["ref"], "sourceEpoch": item["sourceEpoch"]},
                        "state": "eligible",
                        "currentRevision": item["sourceRevision"],
                    }
                    for item in prior["resources"]
                ],
            },
            now=self.fx.now,
        )
        self.rejects("recipient_binding_mismatch", lambda: self.submit())
        self.assertEqual(self.history.owner_list(UID, self.f.vault)["items"], [])

    def test_distinct_second_publication_cannot_create_another_initial_result(self):
        self.submit()
        c = self.output_context(stableOperationId="synthetic_other_result_operation_01")
        self.rejects(
            "initial_result_exists",
            lambda: self.submit(carrier=self.seal(c), operation=c["stableOperationId"]),
        )
        self.assertEqual(len(self.history.owner_list(UID, self.f.vault)["items"]), 1)

    def test_revoked_resource_blocks_new_write_but_not_saved_owner_history(self):
        receipt = self.submit()
        self.fx.apply(self.fx.command(targets=[self.fx.revoke_target()]), revoke=True)
        self.assertEqual(
            self.history.owner_get(UID, self.f.vault, receipt["resultId"])["receipt"], receipt
        )
        self.assertEqual(self.submit(), receipt)
        c = self.output_context(stableOperationId="synthetic_denied_result_operation_01")
        self.rejects(
            "insufficient_scope",
            lambda: self.submit(carrier=self.seal(c), operation=c["stableOperationId"]),
        )

    def test_current_task_output_policy_and_authority_cannot_be_invented(self):
        for change in (
            {"manifestFingerprint": "f" * 64},
            {"authorityVersion": 9},
            {"taskVersion": 2},
        ):
            with self.subTest(change=change):
                c = self.output_context(**change)
                self.rejects(
                    "recipient_binding_mismatch", lambda c=c: self.submit(carrier=self.seal(c))
                )

    def test_only_current_agent_signer_can_submit_and_all_owner_recipients_are_required(self):
        _, payload = _signed_parts(self.carrier["proof"])
        bad = copy.deepcopy(self.carrier)
        bad["proof"] = sign_jws(payload, self.f.keys["device_sig"], typ="fv-control+jws")
        self.rejects("invalid_signature", lambda: self.submit(carrier=bad))
        c = self.output_context(
            recipients=[r for r in self.context["recipients"] if r["role"] == "recovery_enc"]
        )
        # The exact current owner recipient set is required.
        with self.assertRaises(ValueError):
            self.submit(carrier=self.seal(c))

    def test_owner_scope_and_bad_run_selectors_never_leak_ciphertext(self):
        receipt = self.submit()
        self.rejects(
            "not_found",
            lambda: self.history.owner_get(OTHER_UID, self.f.vault, receipt["resultId"]),
        )
        self.rejects("not_found", lambda: self.history.owner_list(OTHER_UID, self.f.vault))
        request = {"runId": "synthetic_foreign_run"}
        self.rejects(
            "not_found",
            lambda: self.service.result_receipt(*self.x.args("runs/result-receipt", request)),
        )

    def test_owner_controls_are_signed_cas_and_replay_returns_original_state(self):
        self.submit()
        ident = self.context["objectId"]
        op = "synthetic_persistent_state_operation_01"
        cmd = self.state_command(op, 0, read=True)
        first = self.history.owner_state(
            UID, self.f.vault, ident, cmd, op, self.f.kid("device_sig")
        )
        self.assertTrue(first["read"])
        op2 = "synthetic_persistent_state_operation_02"
        self.history.owner_state(
            UID,
            self.f.vault,
            ident,
            self.state_command(op2, 1, starred=True),
            op2,
            self.f.kid("device_sig"),
        )
        self.assertEqual(
            self.history.owner_state(UID, self.f.vault, ident, cmd, op, self.f.kid("device_sig")),
            first,
        )
        self.assertTrue(self.history.owner_list(UID, self.f.vault)["items"][0]["starred"])
        op3 = "synthetic_persistent_state_operation_03"
        self.rejects(
            "version_conflict",
            lambda: self.history.owner_state(
                UID,
                self.f.vault,
                ident,
                self.state_command(op3, 0, archived=True),
                op3,
                self.f.kid("device_sig"),
            ),
        )

    def test_owner_history_has_no_agent_submit_or_authentication_method(self):
        self.assertFalse(hasattr(self.history, "submit"))
        self.assertFalse(hasattr(self.history, "authenticate"))

    def test_proof_expiring_during_index_write_rolls_back_report_and_index(self):
        append = self.service._append

        def expired(unit, owner, vault, result):
            append(unit, owner, vault, result)
            self.fx.now += 121

        with patch.object(self.service, "_append", side_effect=expired):
            self.rejects("key_authorization_required", lambda: self.submit())
        self.assertEqual(self.history.owner_list(UID, self.f.vault)["items"], [])
        self.assertEqual(self.submit()["resultId"], self.context["objectId"])

    def test_revoked_identity_does_not_block_google_owner_saved_report(self):
        receipt = self.submit()
        self.x.test_identity_and_connection_revocation_stop_request_proofs()
        saved = self.history.owner_get(UID, self.f.vault, receipt["resultId"])
        self.assertEqual(saved["envelope"], self.carrier)
        self.rejects("key_authorization_required", lambda: self.submit())

    def test_append_pages_are_bounded_and_cursors_survive_later_append(self):
        self.submit()
        original = self.fx.store.transact(
            lambda u: u.get(result_path(self.f.owner, self.f.vault, self.context["objectId"]))
        )
        ids = [self.context["objectId"]]

        def add(unit):
            for number in range(1, 66):
                run = f"synthetic_index_run_{number:04d}"
                ident = result_id(self.f.owner, self.f.vault, run)
                row = copy.deepcopy(original)
                row["context"].update(runId=run, objectId=ident)
                row["metadata"].update(runId=run, resultId=ident)
                row["receipt"].update(runId=run, resultId=ident)
                self.service._append(unit, self.f.owner, self.f.vault, ident)
                unit.put(result_path(self.f.owner, self.f.vault, ident), row)
                ids.append(ident)

        self.fx.store.transact(add)
        page = self.history.owner_list(UID, self.f.vault, limit=17)
        seen = []
        while True:
            seen.extend(item["resultId"] for item in page["items"])
            if page["nextCursor"] is None:
                break
            page = self.history.owner_list(UID, self.f.vault, limit=17, cursor=page["nextCursor"])
        self.assertEqual(seen, list(reversed(ids)))
