"""Selected-task browse receipts keep independent bounded sections and the original checks."""

import unittest
from unittest.mock import patch

import test_persistent_publications as publications
import test_task_center_store as modern
from fixtures import OTHER_UID, UID
from test_oauth import TASK
from test_persistent_identity_store import CONNECTION
from vault_lifecycle_fixtures import LifecycleFixture

from app.fences import FenceService, fence_path
from app.native_transport import NativeConnectionOwnerService
from app.persistent_publications import publication_path
from app.store import SQLiteTransaction, StoreUnavailable, document_path
from app.task_center import TaskCenterOwnerService
from app.task_detail import read_task_detail
from app.task_lifecycle import lifecycle_path
from app.vault_lifecycle import VaultLifecycleService
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json

OPTIONS = {"contractVersion": CONTRACT_VERSION, "includePacket": True, "includeAttribution": True}


class TaskDetailTests(unittest.TestCase):
    def setUp(self):
        self.p = publications.PublicationTests()
        self.p.setUp()
        self.addCleanup(self.p.doCleanups)
        self.p.create_task()
        self.store = self.p.fx.store
        self.owner = TaskCenterOwnerService(self.store, clock=lambda: self.p.fx.now)
        self.vault = self.p.f.vault
        self.subject = self.p.f.owner

    def read(self, **options):
        return read_task_detail(self.owner, UID, self.vault, TASK, {**OPTIONS, **options})

    def publish(self):
        c = self.p.context("task")
        self.p.publish(c)
        key = document_path("hub_oauth_connections", self.subject, CONNECTION)
        self.store.transact(
            lambda u: u.put(key, {**u.get(key), "transportKind": "persistent_runtime"})
        )
        return c

    def add_source(self, source):
        operation = "synthetic_source_create_" + source
        fixture = self.p.f
        return self.p.fx.vaults.create_source(
            UID,
            self.vault,
            source,
            fixture.control(source, operation),
            operation,
            fixture.kid("device_sig"),
        )["source"]["resourceRef"]

    def test_opt_in_adds_only_original_vault_and_current_metadata_in_one_snapshot(self):
        first, second = self.add_source("first"), self.add_source("second")
        before = self.p.fx.vaults.current(UID)
        FenceService(self.store, clock=lambda: self.p.fx.now).invalidate(
            {
                "contractVersion": CONTRACT_VERSION,
                "ownerSubject": self.subject,
                "mutationId": "synthetic_source_invalidate",
                "ref": first,
                "expectedSourceEpoch": 1,
                "newSourceEpoch": 2,
                "reason": "disconnected",
            },
            source_service="portfolio",
        )
        expected = self.p.fx.vaults.current(UID)
        self.assertEqual(before["vault"], expected["vault"])
        self.assertEqual([s["sourceEpoch"] for s in expected["sources"]], [2, 1])
        metadata = self.p.tasks.get(UID, TASK)["metadata"]
        old = self.read(includePacket=False)
        self.assertEqual(
            set(old), {"contractVersion", "profile", "state", "legacy", "attribution", "packet"}
        )
        with (
            patch.object(self.store, "transact", wraps=self.store.transact) as transact,
            patch.object(
                SQLiteTransaction, "get_many", autospec=True, side_effect=SQLiteTransaction.get_many
            ) as batch,
            patch.object(
                SQLiteTransaction, "get", autospec=True, side_effect=SQLiteTransaction.get
            ) as single,
        ):
            value = self.read(includeVault=True, includePacket=False)
        self.assertEqual(transact.call_count, 1)
        self.assertEqual(batch.call_count, 1)
        for ref in (first, second):
            path = fence_path(self.subject, ref)
            self.assertIn(path, batch.call_args.args[1])
            self.assertFalse(any(call.args[1] == path for call in single.call_args_list))
        self.assertEqual(value.pop("taskMetadata"), metadata)
        self.assertEqual(value.pop("vaultResponse"), {"status": "ready", "data": expected})
        self.assertEqual(canonical_json(value), canonical_json(old))

    def test_bad_optional_fence_does_not_hide_task_or_synthesize_a_source_epoch(self):
        ref = self.add_source("held")
        path = fence_path(self.subject, ref)
        self.store.transact(lambda u: u.put(path, {"sourceEpoch": 100}))
        with self.assertRaises(StoreUnavailable):
            self.p.fx.vaults.current(UID)
        old = self.read()
        value = self.read(includeVault=True)
        self.assertEqual(value["vaultResponse"], {"status": "unavailable"})
        self.assertEqual(value["packet"], old["packet"])
        self.assertEqual(value["taskMetadata"], old["packet"]["data"]["metadata"])
        original = SQLiteTransaction.get_many

        def fail_optional_batch(unit, paths):
            if path in paths:
                raise StoreUnavailable
            return original(unit, paths)

        with patch.object(SQLiteTransaction, "get_many", fail_optional_batch):
            self.assertEqual(self.read(includeVault=True), value)
            self.assertEqual(self.read(), old)
        with patch.object(SQLiteTransaction, "get_many", side_effect=StoreUnavailable):
            with self.assertRaises(StoreUnavailable):
                self.read(includeVault=True)

    def test_deleted_archive_requires_the_original_root_approved_history(self):
        lifecycle = VaultLifecycleService(self.store, clock=lambda: self.p.fx.now)
        state = lifecycle.state(UID, self.vault)
        operation = "synthetic_task_detail_archive_delete"
        command = LifecycleFixture.command(self.p.f, state, operation, "archive_delete")
        lifecycle.delete_archive(
            UID, self.vault, {"contractVersion": CONTRACT_VERSION, "command": command}, operation
        )
        expected = self.p.fx.vaults.current(UID)
        self.assertIsNone(expected["vault"]["archive"])
        self.assertEqual(expected["vault"]["version"], state["vaultVersion"])
        self.assertEqual(
            self.read(includeVault=True)["vaultResponse"], {"status": "ready", "data": expected}
        )
        self.store.transact(
            lambda u: u.put(document_path("hub_vault_lifecycle", self.subject, self.vault), {})
        )
        with self.assertRaises(StoreUnavailable):
            self.p.fx.vaults.current(UID)
        with self.assertRaises(StoreUnavailable):
            self.read(includeVault=True)

    def test_vault_budget_falls_back_before_displacing_original_sections(self):
        self.publish()
        old = self.read()
        with patch("app.task_detail._vault_response", return_value={"large": "x" * 1048576}):
            value = self.read(includeVault=True)
        self.assertEqual(value.pop("vaultResponse"), {"status": "unavailable"})
        self.assertEqual(value.pop("taskMetadata"), old["packet"]["data"]["metadata"])
        self.assertEqual(value, old)

    def test_legacy_packet_authority_and_attribution_equal_the_original_reads(self):
        self.publish()
        expected_authority = self.p.service.task_state(UID, self.vault, TASK)
        native = NativeConnectionOwnerService(self.store, clock=lambda: self.p.fx.now)
        expected_attribution = native.native_connections(UID)
        self.assertEqual(len(expected_attribution["connections"]), 1)
        expected_state = self.owner.state(UID, self.vault, TASK)
        expected_packet = self.p.tasks.get(UID, TASK)
        with patch.object(self.store, "transact", wraps=self.store.transact) as transact:
            actual = self.read()
        self.assertEqual(transact.call_count, 1)
        self.assertEqual(actual["state"], expected_state)
        self.assertEqual(actual["packet"], {"status": "ready", "data": expected_packet})
        self.assertEqual(actual["legacy"], {"status": "ready", "data": expected_authority})
        self.assertEqual(actual["attribution"], {"status": "ready", "data": expected_attribution})
        with (
            patch("app.task_detail._attribution", side_effect=AssertionError),
            patch("app.task_detail._response", side_effect=AssertionError),
        ):
            value = self.read(includePacket=False, includeAttribution=False)
            self.assertIsNone(value["packet"])
            self.assertIsNone(value["attribution"])
            self.assertEqual(value["legacy"], actual["legacy"])

    def test_selected_legacy_reads_one_publication_row_and_no_other_connection_records(self):
        c = self.publish()
        original = self.store.transact
        calls = []

        def trace(callback):
            def run(unit):
                get, get_many = unit.get, unit.get_many

                def batch(paths, **options):
                    calls.extend(paths)
                    return get_many(paths, **options)

                def counted(path):
                    calls.append(path)
                    return get(path)

                with patch.object(unit, "get", counted), patch.object(unit, "get_many", batch):
                    return callback(unit)

            return original(run)

        index = document_path("hub_oauth_owners", self.subject)
        # Include another listed ID with no document. Reading the entire inventory would fail.
        self.store.transact(
            lambda u: u.put(
                index, {**u.get(index), "connectionIds": [CONNECTION, "synthetic_other"]}
            )
        )
        with patch.object(self.store, "transact", side_effect=trace):
            value = self.read()
        self.assertEqual(value["attribution"]["status"], "ready")
        self.assertEqual(
            calls.count(publication_path(self.subject, self.vault, c["stableOperationId"])), 1
        )
        self.assertEqual(
            calls.count(document_path("hub_oauth_connections", self.subject, CONNECTION)), 1
        )
        self.assertNotIn(
            document_path("hub_oauth_connections", self.subject, "synthetic_other"), calls
        )

    def test_task_without_any_resources_never_reads_executor_authority(self):
        task = "synthetic_empty_task"
        self.p.tasks.create(
            UID,
            self.p.f.task_body(task=task),
            "synthetic_oauth_task_create_1",
            self.p.f.kid("device_sig"),
        )
        with patch("app.task_detail.stored_task_state", side_effect=AssertionError):
            value = read_task_detail(self.owner, UID, self.vault, task, OPTIONS)
        self.assertIsNone(value["legacy"])
        self.assertIsNone(value["attribution"])
        self.assertEqual(value["packet"]["status"], "ready")

    def test_none_is_confirmed_and_failures_stay_with_their_optional_section(self):
        m = self.read()
        self.assertIsNone(m["legacy"]["data"]["authority"])
        self.assertIsNone(m["attribution"])
        c = self.publish()
        with patch("app.task_detail._response", side_effect=StoreUnavailable):
            value = self.read()
        self.assertEqual(value["packet"], {"status": "unavailable"})
        self.assertEqual(value["legacy"]["status"], "ready")
        path = publication_path(self.subject, self.vault, c["stableOperationId"])
        self.store.transact(lambda u: u.put(path, {**u.get(path), "fingerprint": "wrong"}))
        value = self.read()
        self.assertEqual(value["legacy"], {"status": "unavailable"})
        self.assertIsNone(value["attribution"])
        self.assertEqual(value["packet"]["status"], "ready")
        with patch.object(self.owner, "_state", side_effect=StoreUnavailable):
            with self.assertRaises(StoreUnavailable):
                self.read()

    def test_mismatched_owner_vault_index_and_trash_never_disclose_a_label_or_packet(self):
        self.publish()
        row_path = document_path("hub_oauth_connections", self.subject, CONNECTION)
        self.store.transact(
            lambda u: u.put(row_path, {**u.get(row_path), "vaultId": "other_vault"})
        )
        self.assertEqual(self.read()["attribution"], {"status": "unavailable"})
        for uid, vault in [(OTHER_UID, self.vault), (UID, "another_vault")]:
            for options in (OPTIONS, {**OPTIONS, "includeVault": True}):
                with self.assertRaises(ContractError):
                    read_task_detail(self.owner, uid, vault, TASK, options)
        self.store.transact(
            lambda u: u.put(
                lifecycle_path(self.subject, self.vault), {"version": 1, "tasks": {TASK: "trashed"}}
            )
        )
        with self.assertRaises(ContractError) as error:
            self.read()
        self.assertEqual(error.exception.code, "not_found")
        with self.assertRaises(ContractError) as error:
            self.read(includeVault=True)
        self.assertEqual(error.exception.code, "not_found")

    def test_component_bytes_fall_back_without_truncating_mandatory_evidence(self):
        self.publish()
        with patch(
            "app.task_detail._response",
            return_value={
                "metadata": self.p.tasks.get(UID, TASK)["metadata"],
                "large": "x" * 1048576,
            },
        ):
            value = self.read()
        self.assertEqual(value["packet"], {"status": "unavailable"})
        self.assertEqual(value["legacy"]["status"], "ready")
        with patch.object(self.owner, "_state", return_value={"rules": {"large": "x" * 1048576}}):
            with self.assertRaises(ContractError) as error:
                self.read()
        self.assertEqual(error.exception.code, "payload_too_large")


class ModernTaskDetailTests(unittest.TestCase):
    def test_verified_modern_shape_never_touches_the_unscoped_authority_or_account_inventory(self):
        fixture = modern.TaskCenterStoreTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        reference = fixture.owner.state(UID, fixture.f.vault, TASK)
        self.assertTrue(reference["assignments"])
        with (
            patch("app.task_detail.stored_task_state", side_effect=AssertionError),
            patch("app.task_detail._attribution", side_effect=AssertionError),
        ):
            value = read_task_detail(fixture.owner, UID, fixture.f.vault, TASK, OPTIONS)
        self.assertEqual(value["state"], reference)
        self.assertEqual(value["packet"]["status"], "ready")
        self.assertIsNone(value["legacy"])
        self.assertIsNone(value["attribution"])
