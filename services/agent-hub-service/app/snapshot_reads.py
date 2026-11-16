"""Bounded, explicitly read-only Hub callbacks in ordinary RW transactions.

The first BatchGet also starts the transaction. Real zero-write Commit and the
SDK's commit-only ABORTED retry policy remain in place. The pinned Firestore
2.34.1 parser is imported, not copied or modified; its license remains in that
dependency. Only the first actual ID is reused as retry_transaction; rows and
current authorization do not cross attempts.
"""

import copy

from google.api_core.exceptions import Aborted
from google.cloud.firestore_v1.base_client import _parse_batch_get
from google.cloud.firestore_v1.types import TransactionOptions

from folioview_shared.firestore import BoundedTransaction

from .store import FirestoreTransaction, StoreUnavailable, _batch_paths, _read_document

_MAX_INITIAL_PATHS = 21
_MAX_ATTEMPTS = 3


class _ReadView:
    def __init__(self, unit, initial):
        self._unit, self._initial = unit, initial
        self._closed = False
        self.registry_history_cache = unit.registry_history_cache
        self.registry_prefix_cache = unit.registry_prefix_cache

    def _open(self):
        if self._closed:
            raise StoreUnavailable

    def get(self, path):
        self._open()
        _batch_paths([path])
        return copy.deepcopy(self._initial[path]) if path in self._initial else self._unit.get(path)

    def get_many(self, paths, *, field_paths=None):
        self._open()
        paths = _batch_paths(paths)
        if field_paths is not None:
            # Preserve the original projection validator/reader. These two
            # opt-in callbacks read full documents, not masked history fields.
            return self._unit.get_many(paths, field_paths=field_paths)
        result = {
            path: copy.deepcopy(self._initial[path]) for path in paths if path in self._initial
        }
        missing = [path for path in paths if path not in self._initial]
        if missing:
            result.update(self._unit.get_many(missing))
        if set(result) != set(paths):
            raise StoreUnavailable
        return result

    def put(self, *args, **kwargs):
        raise StoreUnavailable

    def flush(self):
        raise StoreUnavailable

    def close(self):
        self._closed = True
        self._initial = {}
        self._unit = None
        self.registry_history_cache = {}
        self.registry_prefix_cache = None


def _initial_paths(factory):
    paths = _batch_paths(factory())
    if not 1 <= len(paths) <= _MAX_INITIAL_PATHS:
        raise StoreUnavailable
    return paths


def sqlite_snapshot(store, initial_paths, callback):
    def read(unit):
        paths = _initial_paths(initial_paths)
        initial = unit.get_many(paths)
        if set(initial) != set(paths):
            raise StoreUnavailable
        view = _ReadView(unit, initial)
        try:
            return callback(view)
        finally:
            view.close()

    return store.transact(read)


def _cancel(stream):
    if stream is not None:
        cancel = getattr(stream, "cancel", None)
        if callable(cancel):
            cancel()


def _failed(transaction, stream):
    try:
        _cancel(stream)
    finally:
        if transaction.in_progress:
            transaction._rollback()
        else:
            # A response may be lost before any real ID arrives. Never invent
            # an ID or claim that such an unknown server transaction was freed.
            transaction._clean_up()


def _start_and_read(store, transaction, paths, retry_id):
    references = [store.client.document(path) for path in paths]
    expected = {reference._document_path: reference for reference in references}
    options = TransactionOptions(
        read_write=TransactionOptions.ReadWrite(retry_transaction=retry_id or b"")
    )
    stream = None
    try:
        stream = store.client._firestore_api.batch_get_documents(
            request={
                "database": store.client._database_string,
                "documents": list(expected),
                "new_transaction": options,
            },
            metadata=store.client._rpc_metadata,
            retry=None,
            timeout=4,
        )
        seen, result = set(), {}
        for index, response in enumerate(stream):
            if index > len(paths):
                raise StoreUnavailable
            identifier = response.transaction
            if index == 0:
                if type(identifier) is not bytes or not identifier:
                    raise StoreUnavailable
                # This is only the actual ID received from Firestore, never a
                # placeholder to trick a high-level SDK transaction into use.
                transaction._id = identifier
            elif identifier:
                # The protocol permits the ID only in the first response.
                # Even an equal repeated ID must not replace cleanup state.
                raise StoreUnavailable
            kind = response._pb.WhichOneof("result")
            if kind is None:
                if index == 0:
                    continue  # Legal ID-only header; first ID+document is legal too.
                raise StoreUnavailable
            try:
                row = _parse_batch_get(response, expected, store.client)
            except (ValueError, KeyError, TypeError):
                raise StoreUnavailable from None
            name = row.reference._document_path
            if name not in expected or name in seen:
                raise StoreUnavailable
            seen.add(name)
            value = row.to_dict() if row.exists else None
            if row.exists and type(value) is not dict:
                raise StoreUnavailable
            path = expected[name].path
            result[path] = _read_document(value, path=path) if row.exists else None
        if not transaction.in_progress or seen != set(expected):
            raise StoreUnavailable
        return result, stream
    except BaseException:
        _cancel(stream)
        raise


def firestore_snapshot(store, initial_paths, callback):
    first_id = None
    for attempt in range(_MAX_ATTEMPTS):
        transaction = BoundedTransaction(store.client, max_attempts=_MAX_ATTEMPTS)
        stream, view = None, None
        try:
            paths = _initial_paths(initial_paths)
            initial, stream = _start_and_read(store, transaction, paths, first_id)
            if first_id is None:
                first_id = transaction.id
            unit = FirestoreTransaction(transaction, store)
            view = _ReadView(unit, initial)
            del unit, initial  # The view alone owns this attempt's data until close.
            result = callback(view)
        except BaseException:
            _failed(transaction, stream)
            raise
        finally:
            if view is not None:
                view.close()
        try:
            transaction._commit()  # A real, bounded zero-write server Commit.
            return result
        except Aborted as error:
            if attempt + 1 == _MAX_ATTEMPTS:
                try:
                    raise ValueError(
                        f"Failed to commit transaction in {_MAX_ATTEMPTS:d} attempts."
                    ) from error
                except BaseException:
                    _failed(transaction, stream)
                    raise
            # Same as the SDK decorator: an ABORTED commit has ended on the
            # server. Preserve the first real ID for retry_transaction, while
            # discarding all attempt-owned rows/units. No rollback before retry.
            transaction._clean_up()
        except BaseException:
            _failed(transaction, stream)
            raise
