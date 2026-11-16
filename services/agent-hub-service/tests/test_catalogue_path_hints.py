"""Document-key hints reduce reads without retaining any authority or source state."""

import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import test_resource_display as display_fixture
from fixtures import OTHER_UID, UID
from test_resource_display import Sources

from app import catalogue
from app.catalogue import CatalogueService
from app.catalogue_paths import FenceKeyHints
from app.fences import FenceService, fence_path
from app.store import FirestoreHubStore, StoreUnavailable, document_path
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.identity import owner_key


class FenceKeyHintBoundsTests(unittest.TestCase):
    def path(self, index):
        return f"hub_source_fences/{index:064x}"

    def test_immutable_tuples_capacity_and_nonextending_expiry(self):
        now = [10.0]
        hints = FenceKeyHints(clock=lambda: now[0])
        for index in range(65):
            hints.remember(str(index), (self.path(index),))
        self.assertEqual(len(hints._entries), 64)
        self.assertIsNone(hints.get("0"))
        paths = hints.get("1")
        self.assertEqual(paths, (self.path(1),))
        with self.assertRaises(TypeError):
            paths[0] = self.path(99)
        now[0] = 309.999
        self.assertEqual(hints.get("1"), paths)
        now[0] = 310
        self.assertIsNone(hints.get("1"))

    def test_reject_unbounded_duplicate_or_nonfence_hints_and_accept_empty(self):
        hints = FenceKeyHints()
        bad = (
            [self.path(1)],
            tuple(self.path(i) for i in range(11)),
            (self.path(1), self.path(1)),
            ("hub_vaults/" + "0" * 64,),
            (self.path(1) + "/extra",),
            ([],),
        )
        for paths in bad:
            hints.remember("owner", paths)
            self.assertIsNone(hints.get("owner"))
        hints.remember("owner", ())
        self.assertEqual(hints.get("owner"), ())

    def test_threads_share_only_bounded_path_tuples(self):
        hints = FenceKeyHints()

        def run(index):
            owner = str(index % 5)
            hints.remember(owner, (self.path(index),))
            paths = hints.get(owner)
            self.assertTrue(paths is None or type(paths) is tuple)

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(run, range(100)))
        self.assertLessEqual(len(hints._entries), 5)
        self.assertTrue(all(type(entry[1]) is tuple for entry in hints._entries.values()))


class CataloguePathHintTests(unittest.TestCase):
    def setUp(self):
        self.support = display_fixture.ResourceDisplayTests()
        self.support.setUp()
        self.addCleanup(self.support.doCleanups)
        self.f = self.support.f
        self.store = self.support.firestore
        self.rpc = self.support.rpc
        self.client = self.support.client

    def directory(self, store=None, *, clock=None):
        vaults = self.support.vaults(store or self.store)
        if clock is not None:
            vaults.clock = clock
        return CatalogueService(vaults, Sources())

    def sizes(self):
        return [len(args["request"]["documents"]) for kind, args in self.rpc.calls if kind == "get"]

    def assert_no_writes(self):
        self.assertTrue(
            all(not args["request"]["writes"] for kind, args in self.rpc.calls if kind == "commit")
        )

    def replace_ref(self, *, resource="replacement_source"):
        path = document_path("hub_vaults", self.f.owner)
        row = self.store.transact(lambda unit: unit.get(path))
        row["sources"][0]["resourceRef"]["resourceId"] = resource
        self.support.replace(self.store, path, row)
        return row["sources"][0]["resourceRef"]

    def test_actual_sdk_cold_three_to_warm_two_legs_for_one_two_ten_sources(self):
        created = 1
        for count in (1, 2, 10):
            for index in range(created, count):
                source, operation = f"source_{index}", f"synthetic_hints_source_{index:04d}"
                self.support.vaults(self.store).create_source(
                    UID,
                    self.f.vault,
                    source,
                    self.f.control(source, operation),
                    operation,
                    self.f.kid("device_sig"),
                )
            created = count
            self.store._catalogue_fence_keys.discard(self.f.owner)
            self.rpc.calls.clear()
            cold = self.support.service(self.store).read(UID)
            self.assertEqual(self.sizes(), [1, count, 1 + 2 * count])
            self.rpc.calls.clear()
            warm = self.support.service(self.store).read(UID)
            self.assertEqual(self.sizes(), [1 + count, 1 + 2 * count])
            self.assertEqual(warm, cold)
            self.assertEqual(sum(kind == "begin" for kind, _ in self.rpc.calls), 0)
            self.assert_no_writes()

    def test_changed_keys_read_missing_paths_and_discard_old_schema_invalid_fence(self):
        before = self.directory().context(UID)
        old_ref = before["sources"][0]["ref"]
        old_path = fence_path(self.f.owner, old_ref)
        current = self.replace_ref()
        # An obsolete hint's schema never supplies current source data. It is
        # read physically, but only actual paths reach the original _state.
        self.support.replace(self.store, old_path, {"ownerSubject": "foreign_owner"})
        self.rpc.calls.clear()
        after = self.directory().context(UID)
        self.assertEqual(self.sizes(), [2, 1])
        self.assertEqual([source["ref"] for source in after["sources"]], [current])
        self.assertEqual(
            self.store._catalogue_fence_keys.get(self.f.owner), (fence_path(self.f.owner, current),)
        )
        self.assert_no_writes()

    def test_new_source_is_added_in_same_attempt_and_next_request_is_one_batch(self):
        self.directory().context(UID)
        source, operation = "new_source", "synthetic_hints_new_source_0001"
        self.support.vaults(self.store).create_source(
            UID,
            self.f.vault,
            source,
            self.f.control(source, operation),
            operation,
            self.f.kid("device_sig"),
        )
        self.rpc.calls.clear()
        context = self.directory().context(UID)
        self.assertEqual(self.sizes(), [2, 1])
        self.assertEqual(len(context["sources"]), 2)
        self.rpc.calls.clear()
        self.assertEqual(self.directory().context(UID), context)
        self.assertEqual(self.sizes(), [3])

    def test_maximum_disjoint_changed_keys_stay_bounded_and_return_only_real_refs(self):
        for index in range(1, 10):
            source, operation = f"old_source_{index}", f"synthetic_hints_old_source_{index:04d}"
            self.support.vaults(self.store).create_source(
                UID,
                self.f.vault,
                source,
                self.f.control(source, operation),
                operation,
                self.f.kid("device_sig"),
            )
        previous = self.directory().context(UID)
        old_paths = self.store._catalogue_fence_keys.get(self.f.owner)
        self.assertEqual(len(old_paths), 10)
        path = document_path("hub_vaults", self.f.owner)
        row = self.store.transact(lambda unit: unit.get(path))
        for index, source in enumerate(row["sources"]):
            source["resourceRef"]["resourceId"] = f"replaced_source_{index}"
        self.support.replace(self.store, path, row)
        self.rpc.calls.clear()
        result = self.support.service(self.store).read(UID)
        self.assertEqual(self.sizes(), [11, 10, 21])
        expected = [source["resourceRef"] for source in row["sources"]]
        self.assertEqual(
            [item["ref"] for item in result["catalogue"]["groups"][0]["items"]], expected
        )
        self.assertFalse(any(item["ref"] in expected for item in previous["sources"]))
        calls = [args for kind, args in self.rpc.calls if kind == "get"]
        initial = set(calls[0]["request"]["documents"]) | set(calls[1]["request"]["documents"])
        self.assertEqual(len(initial), 21)
        self.assert_no_writes()

    def test_owner_and_store_identity_isolation(self):
        self.directory().context(UID)
        self.rpc.calls.clear()
        self.assertEqual(self.directory().context(OTHER_UID), {"vault": None, "sources": []})
        self.assertEqual(self.sizes(), [1])
        requested = [
            name
            for kind, args in self.rpc.calls
            if kind == "get"
            for name in args["request"]["documents"]
        ]
        self.assertNotIn(
            self.client.document(document_path("hub_vaults", self.f.owner))._document_path,
            requested,
        )
        self.assertIsNone(self.store._catalogue_fence_keys.get(owner_key(OTHER_UID)))
        # Even two Store objects using the same project/database/client have
        # distinct hint ownership. No global identity or per-UID data cache.
        other_store = FirestoreHubStore("synthetic-hub", "agent-hub", client=self.client)
        self.rpc.calls.clear()
        self.directory(other_store).context(UID)
        self.assertEqual(self.sizes(), [1, 1])
        self.assertIsNot(other_store._catalogue_fence_keys, self.store._catalogue_fence_keys)

    def test_expiry_and_unsupported_store_use_original_cold_path(self):
        now = [0.0]
        self.store._catalogue_fence_keys = FenceKeyHints(clock=lambda: now[0])
        self.directory().context(UID)
        now[0] = 300
        self.rpc.calls.clear()
        self.directory().context(UID)
        self.assertEqual(self.sizes(), [1, 1])
        self.store._catalogue_fence_keys = object()
        self.rpc.calls.clear()
        self.directory().context(UID)
        self.assertEqual(self.sizes(), [1, 1])

    def test_retry_reads_fresh_rows_clock_and_changed_keys_without_publishing_aborted_hint(self):
        self.directory().context(UID)
        previous = self.store._catalogue_fence_keys.get(self.f.owner)
        path = document_path("hub_vaults", self.f.owner)
        row = self.store.transact(lambda unit: unit.get(path))
        changed = copy.deepcopy(row)
        changed["sources"][0]["resourceRef"]["incarnation"] = "retry_incarnation"
        # Simulate a concurrently committed trusted row without adding a write
        # to the transaction under test. The history/Root itself stays valid.
        physical = self.rpc.documents[self.client.document(path)._document_path]
        replacement = copy.deepcopy(physical)
        replacement["sources"] = changed["sources"]

        def change():
            self.assertEqual(self.store._catalogue_fence_keys.get(self.f.owner), previous)
            self.rpc.documents[self.client.document(path)._document_path] = replacement

        self.rpc.aborts, self.rpc.before_abort = 1, change
        self.rpc.calls.clear()
        with patch.object(catalogue, "_verify_row", wraps=catalogue._verify_row) as verify:
            current = self.directory(clock=iter((1000, 1001)).__next__).context(UID)
        self.assertEqual([call.args[2] for call in verify.call_args_list], [1000, 1001])
        self.assertEqual(self.sizes(), [2, 2, 1])
        self.assertEqual(current["sources"][0]["ref"]["incarnation"], "retry_incarnation")
        self.assertEqual(
            self.store._catalogue_fence_keys.get(self.f.owner),
            (fence_path(self.f.owner, changed["sources"][0]["resourceRef"]),),
        )
        self.assert_no_writes()

    def test_retry_clock_rollback_or_bad_root_cannot_use_hints_as_authority(self):
        self.directory().context(UID)
        self.rpc.aborts = 1
        with self.assertRaises(ContractError):
            self.directory(clock=iter((1000, 499)).__next__).context(UID)
        self.assertIsNone(self.store._catalogue_fence_keys.get(self.f.owner))
        path = document_path("hub_vaults", self.f.owner)

        def change_root():
            self.rpc.documents[self.client.document(path)._document_path]["rootKeyId"] = "A" * 43

        self.rpc.aborts, self.rpc.before_abort = 1, change_root
        with self.assertRaises(StoreUnavailable):
            self.directory().context(UID)
        self.assertIsNone(self.store._catalogue_fence_keys.get(self.f.owner))

    def test_obsolete_physically_corrupt_hint_fails_once_then_explicit_retry_reads_current(self):
        previous = self.directory().context(UID)
        old_path = fence_path(self.f.owner, previous["sources"][0]["ref"])
        current = self.replace_ref()
        # Bypass the guarded writer only inside the synthetic RPC boundary to
        # represent an already corrupt, now-obsolete stored document.
        self.rpc.documents[self.client.document(old_path)._document_path] = {
            "corrupt": "x" * 786_433
        }
        self.rpc.calls.clear()
        with self.assertRaises(StoreUnavailable):
            self.directory().context(UID)
        self.assertEqual(self.sizes(), [2])
        self.assertIsNone(self.store._catalogue_fence_keys.get(self.f.owner))
        self.assert_no_writes()
        self.rpc.calls.clear()
        result = self.directory().context(UID)
        self.assertEqual(self.sizes(), [1, 1])
        self.assertEqual([source["ref"] for source in result["sources"]], [current])
        self.assert_no_writes()

    def test_physically_corrupt_actual_fence_still_fails_after_hint_is_discarded(self):
        previous = self.directory().context(UID)
        path = fence_path(self.f.owner, previous["sources"][0]["ref"])
        self.rpc.documents[self.client.document(path)._document_path] = {"corrupt": "x" * 786_433}
        self.rpc.calls.clear()
        with self.assertRaises(StoreUnavailable):
            self.directory().context(UID)
        self.assertEqual(self.sizes(), [2])
        self.assertIsNone(self.store._catalogue_fence_keys.get(self.f.owner))
        self.rpc.calls.clear()
        with self.assertRaises(StoreUnavailable):
            self.directory().context(UID)
        self.assertEqual(self.sizes(), [1, 1])
        self.assertIsNone(self.store._catalogue_fence_keys.get(self.f.owner))
        self.assert_no_writes()

    def test_warm_fence_state_is_fresh_and_final_fence_still_rejects_same_version_change(self):
        self.support.service(self.store).read(UID)
        ref = self.support.fixture.ref

        def change(epoch, operation):
            FenceService(self.store, clock=lambda: 1000).invalidate(
                {
                    "contractVersion": CONTRACT_VERSION,
                    "ownerSubject": self.f.owner,
                    "mutationId": operation,
                    "ref": ref,
                    "expectedSourceEpoch": epoch,
                    "newSourceEpoch": epoch + 1,
                    "reason": "account_scope_changed",
                },
                source_service="portfolio",
            )

        change(1, "synthetic_hints_fence_0001")
        warm = self.support.service(self.store).read(UID)
        self.assertEqual(warm["catalogue"]["groups"][0]["items"][0]["sourceEpoch"], 2)
        with self.assertRaises(ContractError) as error:
            self.support.service(
                self.store, Sources(lambda: change(2, "synthetic_hints_fence_0002"))
            ).read(UID)
        self.assertEqual(error.exception.code, "version_conflict")

    def test_partial_hint_batch_remains_fail_closed(self):
        self.directory().context(UID)
        original = self.rpc.batch_get_documents

        def partial(**kwargs):
            rows = list(original(**kwargs))
            return iter(rows[:-1]) if len(kwargs["request"]["documents"]) == 2 else iter(rows)

        with (
            patch.object(self.rpc, "batch_get_documents", partial),
            self.assertRaises(StoreUnavailable),
        ):
            self.directory().context(UID)

    def test_sqlite_parity_and_zero_writes_for_cold_warm_changed_keys(self):
        store = self.support.sqlite
        before = self.support.snapshot(store)
        selected = []
        original = store.connect

        def connect():
            connection = original()
            connection.set_trace_callback(
                lambda statement: (
                    selected.append(statement) if statement.startswith("SELECT ") else None
                )
            )
            return connection

        with patch.object(store, "connect", connect):
            cold = self.support.service(store).read(UID)
            self.assertEqual(len(selected), 3)
            selected.clear()
            warm = self.support.service(store).read(UID)
            self.assertEqual(len(selected), 2)
        self.assertEqual(cold, warm)
        self.assertEqual(before, self.support.snapshot(store))
        self.assertEqual(
            store._catalogue_fence_keys.get(self.f.owner),
            (fence_path(self.f.owner, self.support.fixture.ref),),
        )
        path = document_path("hub_vaults", self.f.owner)
        row = store.transact(lambda unit: unit.get(path))
        row["sources"][0]["resourceRef"]["incarnation"] = "sqlite_new_incarnation"
        self.support.replace(store, path, row)
        current = self.directory(store).context(UID)
        self.assertEqual(current["sources"][0]["ref"]["incarnation"], "sqlite_new_incarnation")


if __name__ == "__main__":
    unittest.main()
