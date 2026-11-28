"""Signed manual intents and real local pickup/Begin/result transactions."""

import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_task_center_store as centers
from fixtures import OTHER_UID, UID
from test_oauth import TASK

from app.manual_intents import ManualAgentService, ManualOwnerService, manual_history, queue_path
from app.persistent_agents import USER_AUTHORITY_TRANSITION
from app.store import StoreUnavailable, document_path, private_resource_writer_fence_path
from app.task_center import center_reference
from app.task_detail import PROFILE as DETAIL_PROFILE
from app.task_detail import read_task_detail
from app.user_vault_authority import CurrentUserVault, ScopedUserVaults
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import _signed_parts, signing_input_fingerprint
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.persistent_content import digest
from folioview_shared.encrypted.task_center import assignment_trigger_id


class ManualIntentTests(unittest.TestCase):
    def setUp(self):
        self.fx = centers.TaskCenterStoreTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.f = self.fx.f
        self.owner = ManualOwnerService(self.fx.store, clock=lambda: self.fx.fx.now)
        self.fx.owner = self.owner
        old = self.fx.agent
        self.agent = ManualAgentService(
            old.store,
            old.catalogue,
            audience=old.audience,
            client_ids=old.client_ids,
            managed_only=True,
            clock=old.clock,
        )
        self.fx.agent = self.agent

    def create(self):
        _, payload = _signed_parts(self.fx.last_signed)
        self.fx.serial += 1
        payload.update(
            action="manual_intent",
            schedule=None,
            assignment=None,
            assignmentId=None,
            expectedAssignmentVersion=None,
            issuedAt=self.fx.fx.now,
            expectedDefinitionVersion=self.fx.definition["definitionVersion"],
            stableOperationId="manual_" + digest([self.fx.serial, self.fx.fx.now]),
            intent={
                "expiresAt": self.fx.fx.now + 600,
                "assignments": sorted(
                    [
                        {
                            "assignmentId": a["assignmentId"],
                            "assignmentVersion": a["assignmentVersion"],
                        }
                        for a in self.fx.assignments.values()
                    ],
                    key=lambda a: a["assignmentId"],
                ),
            },
        )
        self.signed = self.f.sign(payload)
        self.operation = payload["stableOperationId"]
        return self.owner.manual(UID, self.f.vault, TASK, self.signed, self.operation)

    def claim(self, request):
        a = self.fx.assignments[self.fx.connection]
        trigger = assignment_trigger_id(a, request, kind="manual")
        body = {
            "taskId": TASK,
            "baseTriggerId": request,
            "manualIntentId": request,
            "operationId": "begin_" + digest([self.f.owner, self.f.vault, TASK, trigger]),
            "binding": center_reference(self.fx.definition, a),
            "taskPublicationFingerprint": a["authorityFingerprint"],
        }
        return self.agent.prepare(*self.fx.args("task-center/prepare", body))

    def begin(self, request):
        prepared = self.claim(request)
        body = {
            "taskId": TASK,
            "triggerId": prepared["triggerId"],
            "operationId": prepared["request"]["operationId"],
            "taskPublicationFingerprint": prepared["request"]["taskPublicationFingerprint"],
        }
        return self.fx.execution.begin(*self.fx.args("runs/begin", body))

    def test_manual_retry_pickup_restart_and_result_have_owner_provenance(self):
        receipt = self.create()
        self.assertFalse(receipt["dispatchSupported"])
        self.assertEqual(
            self.owner.manual(UID, self.f.vault, TASK, self.signed, self.operation), receipt
        )
        first = self.begin(self.operation)
        self.assertEqual(first, self.begin(self.operation))
        self.assertEqual(
            self.owner.manual_state(UID, self.f.vault, TASK, self.operation)["aggregate"]["state"],
            "running",
        )
        submitted = self.fx.submit(first)
        state = self.owner.manual_state(UID, self.f.vault, TASK, self.operation)
        self.assertEqual(state["aggregate"]["state"], "waiting")
        self.assertEqual(state["aggregate"]["counts"]["result_received"], 1)
        self.fx.use(next(c for c in self.fx.assignments if c != self.fx.connection))
        self.fx.submit(self.begin(self.operation))
        self.assertEqual(
            self.owner.manual_state(UID, self.f.vault, TASK, self.operation)["aggregate"]["state"],
            "result_received",
        )
        feed = self.owner.results(UID, self.f.vault, TASK, {"limit": 20, "cursor": None})
        self.assertEqual({i["attribution"]["trigger"]["kind"] for i in feed["items"]}, {"manual"})
        self.assertEqual(
            state["snapshot"]["executors"][
                next(
                    i
                    for i, e in enumerate(state["snapshot"]["executors"])
                    if e["resultId"] == submitted["resultId"]
                )
            ]["stage"],
            "result_received",
        )

    def transfer_authority(self):
        owner, vault = self.f.owner, self.f.vault
        marker = {
            "ownerSubject": owner,
            "vaultId": vault,
            "state": "transferred",
            "writerEpoch": 2,
            "transitionFingerprint": "d" * 64,
        }

        def transfer(unit):
            for connection in self.fx.assignments:
                path = document_path("hub_oauth_connections", owner, connection)
                unit.put(
                    path,
                    {**unit.get(path), USER_AUTHORITY_TRANSITION: marker["transitionFingerprint"]},
                )
            unit.put(private_resource_writer_fence_path(owner), marker)
            return unit.get(document_path("hub_vaults", owner))

        old = self.fx.store.transact(transfer)
        client = Mock()
        client.read.return_value = CurrentUserVault(
            {
                **old,
                "vaultVersion": old["version"],
                "sources": [
                    {
                        "binding": {"ref": self.f.resource, "sourceEpoch": 1},
                        "state": "active",
                    }
                ],
            },
            SimpleNamespace(registry=self.f.registry),
            marker,
            self.fx.fx.now + 8,
        )
        scopes = ScopedUserVaults(self.fx.store, owner=owner, client=client)
        for service in (self.owner, self.agent, self.fx.execution):
            service.user_vaults = scopes
        return client

    def test_transferred_manual_controls_and_pickup_use_the_current_user_writer(self):
        vault = self.f.vault
        self.transfer_authority()

        receipt = self.create()
        self.assertEqual(self.owner.manual(UID, vault, TASK, self.signed, self.operation), receipt)
        run = self.begin(self.operation)
        self.assertEqual(self.begin(self.operation), run)
        self.assertEqual(
            self.owner.manual_state(UID, vault, TASK, self.operation)["aggregate"]["state"],
            "running",
        )

    def display(self, uid=UID, vault=None):
        return read_task_detail(
            self.owner,
            uid,
            vault or self.f.vault,
            TASK,
            {
                "contractVersion": CONTRACT_VERSION,
                "includePacket": False,
                "includeAttribution": False,
                "includeManual": True,
            },
        )

    def test_display_reads_signed_state_and_history_with_one_current_authority(self):
        vault = self.f.vault
        client = self.transfer_authority()
        for stage in ("empty", "waiting", "running"):
            if stage == "waiting":
                self.create()
            if stage == "running":
                self.begin(self.operation)
            expected = {
                "contractVersion": CONTRACT_VERSION,
                "profile": DETAIL_PROFILE,
                "state": self.owner.state(UID, vault, TASK),
                "manual": self.owner.manual_list(UID, vault, TASK),
            }
            client.reset_mock()
            with (
                patch.object(self.owner, "_owner_task", wraps=self.owner._owner_task) as checked,
                patch.object(self.owner, "_state", wraps=self.owner._state) as state,
                patch("app.task_detail.manual_history", wraps=manual_history) as history,
            ):
                self.assertEqual(self.display(), expected)
            client.read.assert_called_once()
            checked.assert_called_once()
            state.assert_called_once()
            history.assert_called_once()
            self.assertIs(state.call_args.args[0], history.call_args.args[0])
            self.assertIs(checked.call_args.args[0], history.call_args.args[0])

    def test_display_rejects_other_owners_trashed_and_purged_tasks(self):
        with self.assertRaises(ContractError) as error:
            self.display(OTHER_UID)
        self.assertEqual(error.exception.code, "not_found")
        self.fx.definition = self.fx.control("trash")["definition"]
        with self.assertRaises(ContractError) as error:
            self.display()
        self.assertEqual(error.exception.code, "not_found")
        self.fx.definition = self.fx.control("purge")["definition"]
        with self.assertRaises(ContractError) as error:
            self.display()
        self.assertEqual(error.exception.code, "not_found")

    def test_display_rejects_changed_owner_authority_and_vault(self):
        client = self.transfer_authority()
        with self.assertRaises(ContractError) as error:
            self.display(vault="different_vault")
        self.assertEqual(error.exception.code, "source_unavailable")
        # The transaction must reject a writer fence changed after the authority response.
        self.fx.store.transact(
            lambda unit: unit.delete(private_resource_writer_fence_path(self.f.owner))
        )
        with patch.object(self.owner.user_vaults, "read", return_value=client.read.return_value):
            with self.assertRaises(ContractError) as error:
                self.display()
        self.assertEqual(error.exception.code, "source_unavailable")

    def test_display_propagates_failed_or_oversized_history_and_can_retry(self):
        self.create()
        with patch("app.manual_intents._intent", side_effect=StoreUnavailable):
            with self.assertRaises(StoreUnavailable):
                self.display()
        with patch("app.manual_intents._summary", return_value={"tooLarge": "x" * 1048576}):
            with self.assertRaises(ContractError) as error:
                self.display()
        self.assertEqual(error.exception.code, "payload_too_large")
        self.assertEqual(self.display()["manual"], self.owner.manual_list(UID, self.f.vault, TASK))

    def test_display_rejects_invalid_stored_queues_before_reading_intents(self):
        path = queue_path(self.f.owner, self.f.vault, TASK)
        for row in (
            {},
            {"ids": "invalid"},
            {"ids": ["invalid-id"]},
            {"ids": ["synthetic_run_request_01"] * 2},
            {"ids": [f"synthetic_run_request_{i:02d}" for i in range(17)]},
        ):
            with self.subTest(row=row):
                self.fx.store.transact(lambda unit, value=row: unit.put(path, value))
                with patch("app.manual_intents._intent", side_effect=AssertionError):
                    with self.assertRaises(StoreUnavailable):
                        self.display()
                    with self.assertRaises(StoreUnavailable):
                        self.owner.manual_list(UID, self.f.vault, TASK)

    def test_cancel_before_claim_is_idempotent_and_fences_late_pickup(self):
        self.create()
        self.assertEqual(
            self.owner.cancel_manual(UID, self.f.vault, TASK, self.operation),
            self.owner.cancel_manual(UID, self.f.vault, TASK, self.operation),
        )
        with self.assertRaises(ContractError):
            self.claim(self.operation)
        with self.assertRaises(ContractError):
            self.owner.manual_state(OTHER_UID, self.f.vault, TASK, self.operation)

    def test_claim_and_cancel_race_never_starts_a_cancelled_intent(self):
        self.create()

        def cancel():
            try:
                return self.owner.cancel_manual(UID, self.f.vault, TASK, self.operation)
            except ContractError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(cancel)
            try:
                self.claim(self.operation)
                claimed = True
            except ContractError:
                claimed = False
            result = pending.result()
        self.assertNotEqual(claimed, result is not None)
        if result:
            with self.assertRaises(ContractError):
                self.begin(self.operation)

    def test_expiry_and_trash_restore_do_not_replay_unclaimed_requests(self):
        self.create()
        self.fx.fx.now += 600
        state = self.owner.manual_state(UID, self.f.vault, TASK, self.operation)
        self.assertTrue(all(v == "timed_out" for v in state["reasons"].values()))
        with self.assertRaises(ContractError):
            self.claim(self.operation)
        self.fx.definition = self.fx.control("trash")["definition"]
        with self.assertRaises(ContractError):
            self.owner.manual_list(UID, self.f.vault, TASK)
        self.fx.definition = self.fx.control("restore")["definition"]
        with self.assertRaises(ContractError):
            self.claim(self.operation)

    def test_fifo_is_per_actor_and_manual_namespace_is_separate(self):
        first = self.create()["requestId"]
        second = self.create()["requestId"]
        with self.assertRaises(ContractError):
            self.claim(second)
        run = self.begin(first)
        # An unverified scheduled/legacy request with the same public base has
        # its own namespace; manual pickup does not consume or relabel it.
        legacy = self.fx.begin(first)
        self.assertNotEqual(run["manifest"]["runId"], legacy["manifest"]["runId"])
        self.fx.submit(run)
        self.assertIsNotNone(self.begin(second)["manifest"])

    def test_deleted_pending_and_inflight_intents_are_not_reactivated_by_restore(self):
        request = self.create()["requestId"]
        run = self.begin(request)
        self.fx.definition = self.fx.control("trash")["definition"]
        with self.assertRaises(ContractError):
            self.fx.submit(run)
        self.fx.definition = self.fx.control("restore")["definition"]
        with self.assertRaises(ContractError):
            self.claim(request)

    def test_owner_queue_is_bounded_and_cancelled_slot_can_be_reused(self):
        receipts = [self.create() for _ in range(16)]
        with self.assertRaises(ContractError):
            self.create()
        self.owner.cancel_manual(UID, self.f.vault, TASK, receipts[0]["requestId"])
        self.create()
        self.assertEqual(len(self.owner.manual_list(UID, self.f.vault, TASK)["items"]), 16)

    def test_durable_pickup_remains_valid_after_control_admission_freshness_window(self):
        request = self.create()["requestId"]
        self.fx.fx.now += 599
        self.assertIsNotNone(self.begin(request)["manifest"])

    def test_cancel_never_submitted_command_fences_delayed_submission(self):
        self.fx.control("set_rules")
        signed, operation = self.fx.last_signed, self.fx.last_op
        # A fresh signed command with no accepted receipt.
        _, payload = _signed_parts(signed)
        payload["stableOperationId"] = "never_submitted_operation"
        payload["expectedDefinitionVersion"] = self.fx.definition["definitionVersion"]
        signed = self.f.sign(payload)
        operation = payload["stableOperationId"]
        fp = signing_input_fingerprint(signed)
        first = self.owner.cancel_operation(UID, self.f.vault, TASK, operation, fp)
        self.assertEqual(first["state"], "cancelled")
        self.assertEqual(first, self.owner.cancel_operation(UID, self.f.vault, TASK, operation, fp))
        with self.assertRaises(ContractError):
            self.owner.command(UID, self.f.vault, TASK, signed, operation)
        with self.assertRaises(ContractError):
            self.owner.cancel_operation(UID, self.f.vault, TASK, operation, "a" * 43)
        with self.assertRaises(ContractError):
            self.owner.cancel_operation(OTHER_UID, self.f.vault, TASK, operation, fp)

    def test_committed_command_and_manual_return_original_receipt(self):
        receipt = self.owner.receipt(UID, self.f.vault, TASK, self.fx.last_op)
        outcome = self.owner.cancel_operation(
            UID, self.f.vault, TASK, self.fx.last_op, signing_input_fingerprint(self.fx.last_signed)
        )
        self.assertEqual(outcome["state"], "committed")
        self.assertEqual(outcome["receipt"], receipt)
        manual = self.create()
        outcome = self.owner.cancel_operation(
            UID, self.f.vault, TASK, self.operation, signing_input_fingerprint(self.signed)
        )
        self.assertEqual(outcome["state"], "committed")
        self.assertEqual(outcome["receipt"], manual)

    def test_cancellation_races_manual_submission_without_replacement(self):
        self.create()
        _, payload = _signed_parts(self.signed)
        payload["stableOperationId"] = "racing_unconfirmed_manual"
        signed = self.f.sign(payload)
        operation, fp = payload["stableOperationId"], signing_input_fingerprint(signed)

        def submit():
            try:
                return self.owner.manual(UID, self.f.vault, TASK, signed, operation)
            except ContractError as error:
                return error.code

        def cancel():
            return self.owner.cancel_operation(UID, self.f.vault, TASK, operation, fp)

        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(submit), pool.submit(cancel)
            result, outcome = a.result(), b.result()
        if outcome["state"] == "committed":
            self.assertEqual(result, outcome["receipt"])
        else:
            self.assertEqual(result, "idempotency_conflict")
            self.assertEqual(outcome["state"], "cancelled")
        self.assertEqual(cancel(), outcome)


class InactiveLegacyTaskLifecycleTests(unittest.TestCase):
    def test_paused_and_archived_legacy_tasks_can_be_trashed_without_reactivation(self):
        from types import SimpleNamespace

        import test_tasks as legacy

        for action, status in [("pause", "paused"), ("archive", "archived")]:
            with self.subTest(status=status):
                old = legacy.TaskTests()
                old.setUp()
                self.addCleanup(old.doCleanups)
                old.save()
                operation = "legacy_lifecycle_transition_0001"
                old.save(
                    old.fixture.body(version=2, operation=operation, action=action, epoch=2),
                    operation=operation,
                    mode="transition",
                )
                owner = ManualOwnerService(old.store, clock=lambda old=old: old.clock)
                signer = SimpleNamespace(
                    serial=0,
                    definition=None,
                    f=old.fixture,
                    fx=SimpleNamespace(now=old.clock),
                    owner=owner,
                )

                def control(action, signer=signer):
                    receipt = centers.TaskCenterStoreTests.control(
                        signer, action, task=legacy.TASK, taskVersion=2, executionEpoch=2
                    )
                    signer.definition = receipt["definition"]
                    return receipt

                control("set_rules")
                control("trash")
                self.assertEqual(old.service.list(UID)["items"], [])
                control("restore")
                self.assertEqual(old.service.get(UID, legacy.TASK)["metadata"]["status"], status)
                self.assertEqual(
                    owner.state(UID, old.fixture.vault, legacy.TASK)["assignments"], []
                )
