"""Real SDK/protobuf streams preserve ordinary RW snapshot lifecycle semantics."""

import asyncio
import copy
import unittest

from google.api_core.exceptions import Aborted, DeadlineExceeded
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from google.cloud.firestore_v1.types import BatchGetDocumentsResponse
from test_firestore_store import MemoryRpc

from app.store import FirestoreHubStore, StoreUnavailable, document_path


class Stream:
    def __init__(self, values, events):
        self.values = iter(values)
        self.events = events
        self.cancelled = False

    def __iter__(self):
        return self

    def __next__(self):
        value = next(self.values)
        if isinstance(value, BaseException):
            raise value
        return value

    def cancel(self):
        self.cancelled = True
        self.events.append("cancel")
        return True


class SnapshotRpc(MemoryRpc):
    def __init__(self, client):
        super().__init__(client)
        self.events, self.streams = [], []
        self.ids = [b"actual-snapshot-one", b"actual-snapshot-two", b"actual-snapshot-three"]
        self.starts = 0
        self.transform = None
        self.open_error = None
        self.commit_error = None
        self.rollback_error = None

    def record(self, kind, kwargs):
        super().record(kind, kwargs)
        self.events.append(kind)

    def batch_get_documents(self, **kwargs):
        rows = list(super().batch_get_documents(**kwargs))
        if "new_transaction" not in kwargs["request"]:
            return iter(rows)
        if self.open_error:
            raise self.open_error
        # The shared fixture supports ordinary combined starts too; this class
        # supplies its own controlled real-ID header and stream mutations.
        if rows and rows[0].transaction:
            rows = rows[1:]
        identifier = (
            self.ids[self.starts]
            if self.starts < len(self.ids)
            else f"actual-snapshot-{self.starts}".encode()
        )
        self.starts += 1
        frames = [BatchGetDocumentsResponse(transaction=identifier), *rows]
        if self.transform:
            frames = self.transform(frames)
        stream = Stream(frames, self.events)
        self.streams.append(stream)
        return stream

    def commit(self, **kwargs):
        if self.commit_error:
            self.record("commit", kwargs)
            raise self.commit_error
        return super().commit(**kwargs)

    def rollback(self, **kwargs):
        if self.rollback_error:
            self.record("rollback", kwargs)
            raise self.rollback_error
        return super().rollback(**kwargs)


class SnapshotReadTests(unittest.TestCase):
    def setUp(self):
        self.client = firestore.Client(
            project="synthetic-hub", database="agent-hub", credentials=AnonymousCredentials()
        )
        self.addCleanup(self.client.close)
        self.rpc = SnapshotRpc(self.client)
        self.client._firestore_api_internal = self.rpc
        self.store = FirestoreHubStore("synthetic-hub", "agent-hub", client=self.client)
        self.path = document_path("hub_vaults", "synthetic_owner")
        self.extra = document_path("hub_source_fences", "synthetic_owner", "source")
        self.rpc.documents[self.name(self.path)] = {"counter": 1}

    def name(self, path):
        return self.client.document(path)._document_path

    def run_read(self, callback=None):
        return self.store.read_snapshot(
            lambda: [self.path], callback or (lambda unit: unit.get(self.path))
        )

    def calls(self, kind):
        return [kwargs for operation, kwargs in self.rpc.calls if operation == kind]

    def test_real_id_only_header_and_missing_doc_commit_in_two_rpcs(self):
        result = self.store.read_snapshot(
            lambda: [self.path, self.extra],
            lambda unit: unit.get_many([self.path, self.extra]),
        )
        self.assertEqual(result, {self.path: {"counter": 1}, self.extra: None})
        self.assertEqual([kind for kind, _ in self.rpc.calls], ["get", "commit"])
        request = self.calls("get")[0]["request"]
        self.assertEqual(request["new_transaction"]._pb.WhichOneof("mode"), "read_write")
        self.assertEqual(request["new_transaction"].read_write.retry_transaction, b"")
        self.assertEqual(self.calls("commit")[0]["request"]["transaction"], self.rpc.ids[0])
        self.assertEqual(list(self.calls("commit")[0]["request"]["writes"]), [])

    def test_first_frame_may_contain_actual_id_and_document(self):
        def combine(frames):
            frames[1].transaction = frames[0].transaction
            return frames[1:]

        self.rpc.transform = combine
        self.assertEqual(self.run_read(), {"counter": 1})
        self.assertEqual(len(self.calls("commit")), 1)
        self.rpc.documents.clear()
        self.assertIsNone(self.run_read())
        self.assertEqual(len(self.calls("commit")), 2)

    def test_supplementary_reads_keep_exact_transaction_and_missing_documents(self):
        result = self.run_read(lambda unit: unit.get_many([self.path, self.extra]))
        self.assertEqual(result[self.path], {"counter": 1})
        self.assertIsNone(result[self.extra])
        self.assertEqual([kind for kind, _ in self.rpc.calls], ["get", "get", "commit"])
        self.assertEqual(self.calls("get")[1]["request"]["transaction"], self.rpc.ids[0])

    def test_partial_duplicate_foreign_and_late_id_frames_cancel_then_rollback(self):
        modes = ("partial", "duplicate", "foreign", "same_id", "different_id", "empty_tail")
        for mode in modes:
            with self.subTest(mode=mode):
                self.rpc.calls.clear()
                self.rpc.events.clear()
                self.rpc.starts = 0

                def change(frames, mode=mode):
                    if mode == "partial":
                        return frames[:1]
                    if mode == "duplicate":
                        return [*frames, copy.deepcopy(frames[1])]
                    if mode == "foreign":
                        frames[1].found.name = self.name(self.extra)
                    elif mode in {"same_id", "different_id"}:
                        frames[1].transaction = self.rpc.ids[0] if mode == "same_id" else b"other"
                    elif mode == "empty_tail":
                        return [*frames, BatchGetDocumentsResponse()]
                    return frames

                self.rpc.transform = change
                with self.assertRaises(StoreUnavailable):
                    self.run_read()
                self.assertEqual(len(self.calls("commit")), 0)
                self.assertEqual(
                    self.calls("rollback")[0]["request"]["transaction"], self.rpc.ids[0]
                )
                self.assertLess(self.rpc.events.index("cancel"), self.rpc.events.index("rollback"))

    def test_unknown_id_open_failure_or_bad_first_frame_never_rolls_back_none(self):
        original = DeadlineExceeded("Synthetic transport before any known ID")
        self.rpc.open_error = original
        with self.assertRaises(DeadlineExceeded) as caught:
            self.run_read()
        self.assertIs(caught.exception, original)
        self.assertEqual(self.calls("rollback"), [])
        self.assertEqual(self.calls("commit"), [])
        self.rpc.open_error = None
        self.rpc.transform = lambda frames: frames[1:]  # Document with no transaction ID.
        with self.assertRaises(StoreUnavailable):
            self.run_read()
        self.assertEqual(self.calls("rollback"), [])
        self.assertTrue(self.rpc.streams[-1].cancelled)

    def test_id_plus_bad_physical_document_rolls_back_the_received_id(self):
        self.rpc.documents[self.name(self.path)] = {"oversized": "x" * 786_433}

        def combine(frames):
            frames[1].transaction = frames[0].transaction
            return frames[1:]

        self.rpc.transform = combine
        with self.assertRaises(StoreUnavailable):
            self.run_read()
        self.assertEqual(self.calls("rollback")[0]["request"]["transaction"], self.rpc.ids[0])
        self.assertTrue(self.rpc.streams[-1].cancelled)

    def test_stream_failure_after_known_id_is_not_a_callback_or_commit_retry(self):
        original = Aborted("Synthetic read-stream abort")
        self.rpc.transform = lambda frames: [frames[0], original]
        with self.assertRaises(Aborted) as caught:
            self.run_read()
        self.assertIs(caught.exception, original)
        self.assertEqual(self.rpc.starts, 1)
        self.assertEqual(len(self.calls("rollback")), 1)
        self.assertEqual(self.calls("commit"), [])

    def test_commit_aborted_retries_factory_rows_and_units_with_original_first_id(self):
        self.rpc.aborts = 2
        factories, views, units, counters = [], [], [], []

        def update():
            self.rpc.documents[self.name(self.path)]["counter"] += 1

        self.rpc.before_abort = update

        def paths():
            factories.append(True)
            return [self.path]

        def callback(unit):
            views.append(unit)
            units.append(unit._unit)
            counters.append(unit.get(self.path)["counter"])
            return counters[-1]

        self.assertEqual(self.store.read_snapshot(paths, callback), 3)
        self.assertEqual(counters, [1, 2, 3])
        self.assertEqual(len(factories), 3)
        self.assertEqual(len({id(unit) for unit in units}), 3)
        requests = [
            item["request"]["new_transaction"].read_write.retry_transaction
            for item in self.calls("get")
        ]
        self.assertEqual(requests, [b"", self.rpc.ids[0], self.rpc.ids[0]])
        self.assertEqual(
            [item["request"]["transaction"] for item in self.calls("commit")], self.rpc.ids
        )
        self.assertEqual(self.calls("begin"), [])
        self.assertEqual(self.calls("rollback"), [])
        for view in views:
            with self.assertRaises(StoreUnavailable):
                view.get(self.path)

    def test_same_server_id_on_distinct_attempts_is_not_artificially_refused(self):
        self.rpc.ids = [b"same-actual-id"] * 3
        self.rpc.aborts = 1
        self.assertEqual(self.run_read(), {"counter": 1})
        self.assertEqual(len(self.calls("commit")), 2)

    def test_only_commit_aborted_retries_and_max_three_matches_original_error(self):
        original = Aborted("Synthetic callback error")

        def fail(unit):
            raise original

        with self.assertRaises(Aborted) as caught:
            self.run_read(fail)
        self.assertIs(caught.exception, original)
        self.assertEqual(self.rpc.starts, 1)
        self.rpc.starts = 0
        self.rpc.calls.clear()
        self.rpc.aborts = 3
        with self.assertRaisesRegex(
            ValueError, "Failed to commit transaction in 3 attempts"
        ) as exhausted:
            self.run_read()
        self.assertIsInstance(exhausted.exception.__cause__, Aborted)
        self.assertEqual(len(self.calls("commit")), 3)
        self.assertEqual(self.calls("rollback")[0]["request"]["transaction"], self.rpc.ids[2])

    def test_cancelled_callback_and_failed_rollback_never_succeed(self):
        cancelled = asyncio.CancelledError("Synthetic callback cancellation")

        def cancel(unit):
            raise cancelled

        with self.assertRaises(asyncio.CancelledError) as caught:
            self.run_read(cancel)
        self.assertIs(caught.exception, cancelled)
        self.assertEqual(len(self.calls("rollback")), 1)
        self.assertEqual(self.calls("commit"), [])
        self.rpc.rollback_error = RuntimeError("Synthetic rollback unavailable")
        with self.assertRaisesRegex(RuntimeError, "Synthetic rollback unavailable"):
            self.run_read(cancel)
        self.assertEqual(self.calls("commit"), [])

    def test_readonly_write_guard_and_initial_only_bounds_do_not_cap_legal_supplement(self):
        def write(unit):
            unit.put(self.path, {"counter": 2})

        with self.assertRaises(StoreUnavailable):
            self.run_read(write)
        with self.assertRaises(StoreUnavailable):
            self.run_read(lambda unit: unit.flush())
        self.assertEqual(self.calls("commit"), [])
        self.rpc.calls.clear()
        initial = [self.path] + [
            document_path("hub_source_fences", "old", str(i)) for i in range(10)
        ]
        actual = [document_path("hub_source_fences", "actual", str(i)) for i in range(10)]
        lifecycle = document_path("hub_vault_lifecycle", "owner", "vault")

        def callback(unit):
            self.assertEqual(set(unit.get_many(actual)), set(actual))
            self.assertIsNone(unit.get(lifecycle))

        self.store.read_snapshot(lambda: initial, callback)
        self.assertEqual(
            [len(item["request"]["documents"]) for item in self.calls("get")], [11, 10, 1]
        )
        self.assertEqual(sum(len(item["request"]["documents"]) for item in self.calls("get")), 22)
        self.rpc.calls.clear()
        with self.assertRaises(StoreUnavailable):
            self.store.read_snapshot(lambda: initial + actual + [lifecycle], callback)
        self.assertEqual(self.calls("get"), [])
        self.assertEqual(self.calls("rollback"), [])


if __name__ == "__main__":
    unittest.main()
