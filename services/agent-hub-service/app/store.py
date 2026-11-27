"""Bounded, atomic storage for ciphertext and trusted public authority replicas."""

import copy
import hashlib
import os
import sqlite3
from contextlib import closing
from functools import lru_cache
from pathlib import Path

from folioview_shared.encrypted.budgets import check_document_budget
from folioview_shared.encrypted.constants import MAX_READ_BYTES, MAX_STORED_DOCUMENT_BYTES
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json, strict_json_loads
from folioview_shared.encrypted.reference_history import (
    decode_reference_history,
    encode_reference_history,
)
from folioview_shared.encrypted.reference_history_v2 import (
    MAX_EXPANDED_HISTORY_BYTES,
    STORAGE_HISTORY_V2_FORMAT,
    decode_storage_history_v2,
)

from .account_writes import (
    HOLDS,
    OWNERSHIP,
    OwnedPath,
    index_path,
    plan_write,
    scoped_path,
    validate_writes,
)
from .catalogue_paths import FenceKeyHints
from .registry_reads import RegistryPrefixCache

COLLECTIONS = frozenset(
    {
        HOLDS,
        OWNERSHIP,
        "hub_vaults",
        "hub_private_display_names",
        "hub_private_resource_writer_fences",
        "hub_private_display_name_operations",
        "hub_agent_recoveries",
        "hub_executor_connections",
        "hub_executor_owners",
        "hub_runtime_setup_intents",
        "hub_runtime_setup_heads",
        "hub_native_oauth_pending",
        "hub_native_oauth_codes",
        "hub_native_oauth_access",
        "hub_native_oauth_refresh",
        "hub_native_oauth_families",
        "hub_persistent_publications",
        "hub_persistent_runs",
        "hub_persistent_plans",
        "hub_persistent_plan_operations",
        "hub_persistent_plan_quotas",
        "hub_persistent_results",
        "hub_persistent_result_content",
        "hub_persistent_result_operations",
        "hub_persistent_result_indexes",
        "hub_persistent_result_pages",
        "hub_persistent_result_state_operations",
        "hub_persistent_run_operations",
        "hub_persistent_run_quotas",
        "hub_persistent_task_authorities",
        "hub_persistent_source_publications",
        "hub_resource_consents",
        "hub_resource_consent_operations",
        "hub_agent_identities",
        "hub_agent_identity_history",
        "hub_agent_credential_operations",
        "hub_agent_credential_setups",
        "hub_agent_credential_limits",
        "hub_center_tasks",
        "hub_center_intents",
        "hub_center_intent_queues",
        "hub_center_lifecycle",
        "hub_erased_task_keys",
        "hub_center_assignments",
        "hub_center_operations",
        "hub_center_preparations",
        "hub_center_triggers",
        "hub_center_plans",
        "hub_center_plan_operations",
        "hub_center_result_indexes",
        "hub_center_result_pages",
        "hub_provider_slots",
        "hub_provider_slot_operations",
        "hub_credential_lineage",
        "hub_agent_identity_operations",
        "hub_vault_lifecycle",
        "hub_operations",
        "hub_source_fences",
        "hub_erased_sources",
        "hub_fence_mutations",
        "hub_tasks",
        "hub_task_versions",
        "hub_task_operations",
        "hub_task_indexes",
        "hub_upload_cancellations",
        "hub_oauth_pending",
        "hub_oauth_codes",
        "hub_oauth_access",
        "hub_oauth_refresh",
        "hub_oauth_families",
        "hub_oauth_connections",
        "hub_oauth_owners",
        "hub_preparations",
        "hub_preparation_objects",
        "hub_task_deliveries",
        "hub_runs",
        "hub_run_components",
        "hub_run_proofs",
        "hub_run_operations",
        "hub_run_indexes",
        "hub_run_quotas",
        "hub_results",
        "hub_result_revisions",
        "hub_result_operations",
        "hub_result_indexes",
        "hub_inbox_cursors",
        "hub_result_state_operations",
    }
)


class StoreUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("Hub storage is temporarily unavailable.")


def document_id(*parts: str) -> str:
    return hashlib.sha256(canonical_json(list(parts))).hexdigest()


def document_path(collection: str, *parts: str) -> str:
    if collection not in COLLECTIONS:
        raise ValueError("Invalid Hub collection.")
    return scoped_path(collection, f"{collection}/{document_id(*parts)}", parts)


def private_resource_writer_fence_path(owner: str) -> str:
    return document_path("hub_private_resource_writer_fences", owner)


def require_legacy_private_writer(unit, owner: str) -> None:
    """Bind a new legacy resource commit to the account's writer fence.

    The missing-document read must be in the same transaction as the writes.
    Firestore retries a conflicting commit and SQLite serializes it with a freeze.
    Existing receipts are resolved before this check.
    """
    if unit.get(private_resource_writer_fence_path(owner)) is not None:
        raise ContractError("authorization_unavailable")


def require_legacy_archive_reader(unit, owner: str) -> None:
    """Allow the original Passkey review through the freeze and close it after transfer."""
    fence = unit.get(private_resource_writer_fence_path(owner))
    if fence is None or (type(fence) is dict and fence.get("state") == "frozen"):
        return
    if type(fence) is dict and fence.get("state") == "transferred":
        raise ContractError("not_found")
    raise ContractError("authorization_unavailable")


# These are logical read ceilings, not HTTP or physical storage write budgets.
# A frozen Run also contains its independently bounded manifest and other fields.
_HISTORY_COLLECTIONS = frozenset({"hub_vaults", "hub_persistent_runs"})
_MAX_EXPANDED_RUN_BYTES = MAX_STORED_DOCUMENT_BYTES + MAX_READ_BYTES
_MAX_EXPANDED_V2_ROW_BYTES = MAX_STORED_DOCUMENT_BYTES + MAX_EXPANDED_HISTORY_BYTES


def _read_document(value: dict, *, path: str) -> dict:
    """Restore bounded untrusted history before the original authority checks.

    Only Vaults and frozen Runs recognize reference history. Reads never write
    or migrate a row. Current writers retain storage.v1 and its original logical
    ceilings; only an explicit storage.v2 value opts into larger local reads.
    """
    try:
        if type(value) is not dict:
            raise StoreUnavailable
        # Own the complete storage snapshot. Preserve Python numeric types for
        # strict authority predicates; JCS must only validate/count, not reparse
        # a native 1.0 or -0.0 into an integer before those checks.
        value = copy.deepcopy(value)
        collection = path.split("/", 1)[0]
        if collection not in _HISTORY_COLLECTIONS or "registryHistory" not in value:
            if len(canonical_json(value)) > MAX_STORED_DOCUMENT_BYTES:
                raise StoreUnavailable
            return value

        history = value["registryHistory"]
        other = canonical_json({**value, "registryHistory": []})
        if len(other) > MAX_STORED_DOCUMENT_BYTES:
            raise StoreUnavailable
        physical_history_bytes = (
            len(history) if type(history) is bytes else len(canonical_json(history))
        )
        if len(other) - 2 + physical_history_bytes > MAX_STORED_DOCUMENT_BYTES:
            raise StoreUnavailable
        if type(history) is bytes:
            # Inspect only the private, strict canonical snapshot. Native dicts
            # must not make this round trip: it would normalize float references.
            parsed = strict_json_loads(history, max_bytes=MAX_STORED_DOCUMENT_BYTES)
            if canonical_json(parsed) != history:
                raise StoreUnavailable
            history = parsed
        if type(history) is dict and history.get("format") == STORAGE_HISTORY_V2_FORMAT:
            remaining = min(MAX_EXPANDED_HISTORY_BYTES, _MAX_EXPANDED_V2_ROW_BYTES - len(other) + 2)
            value["registryHistory"] = decode_storage_history_v2(
                history, max_expanded_bytes=remaining
            )
            return value
        maximum = MAX_READ_BYTES if collection == "hub_vaults" else _MAX_EXPANDED_RUN_BYTES
        remaining = min(MAX_READ_BYTES, maximum - len(other) + 2)
        value["registryHistory"] = decode_reference_history(history, max_expanded_bytes=remaining)
        return value
    except (ContractError, RecursionError):
        raise StoreUnavailable from None


def _firestore_document(value: dict, *, path: str) -> dict:
    if path.split("/", 1)[0] in {"hub_vaults", "hub_persistent_runs"} and type(
        value.get("registryHistory")
    ) in {list, dict}:
        return {**value, "registryHistory": canonical_json(value["registryHistory"])}
    return value


def stored_document(value: dict, *, path: str, project: str, database: str) -> dict:
    """Account for the exact SDK Document, not a JSON-only size estimate.

    No client, credentials or RPC is constructed. Ciphertext is one JSON string,
    rather than a deeply indexed map. Deployment must exempt that opaque field
    from indexing before private content is enabled.
    """
    from google.cloud.firestore_v1._helpers import encode_dict
    from google.cloud.firestore_v1.types import Document

    collection = path.split("/", 1)[0]
    if collection in _HISTORY_COLLECTIONS and "registryHistory" in value:
        # The caller already performed its original authority/CAS checks. Only
        # the internal representation changes, within the reader's exact bounds.
        data = copy.deepcopy(value)
        other_size = len(canonical_json({**data, "registryHistory": []}))
        if other_size > MAX_STORED_DOCUMENT_BYTES:
            raise ContractError("payload_too_large")
        maximum = MAX_READ_BYTES if collection == "hub_vaults" else _MAX_EXPANDED_RUN_BYTES
        data["registryHistory"] = encode_reference_history(
            data["registryHistory"],
            max_expanded_bytes=min(MAX_READ_BYTES, maximum - other_size + 2),
        )
    else:
        data = strict_json_loads(canonical_json(value), max_bytes=MAX_STORED_DOCUMENT_BYTES)
    name = f"projects/{project}/databases/{database}/documents/{path}"
    encoded = Document(
        name=name, fields=encode_dict(_firestore_document(data, path=path))
    )._pb.SerializeToString()
    check_document_budget(data, encoded_document=encoded)
    return data


def _batch_paths(paths):
    if type(paths) not in {list, tuple} or len(paths) > 1024:
        raise StoreUnavailable
    for path in paths:
        if type(path) not in (str, OwnedPath):
            raise StoreUnavailable
        parts = path.split("/")
        if (
            len(parts) != 2
            or parts[0] not in COLLECTIONS
            or len(parts[1]) != 64
            or any(char not in "0123456789abcdef" for char in parts[1])
        ):
            raise StoreUnavailable
    if len(paths) != len(set(paths)):
        raise StoreUnavailable
    return tuple(paths)


def _batch_fields(field_paths):
    if field_paths is None:
        return None
    if (
        type(field_paths) not in {list, tuple}
        or len(field_paths) != 4
        or set(field_paths) != {"ownerSubject", "resultId", "revision", "receipt"}
    ):
        raise StoreUnavailable
    return tuple(field_paths)


def _project(value, field_paths):
    if field_paths is None:
        return value
    try:
        return {field: value[field] for field in field_paths}
    except KeyError:
        raise StoreUnavailable from None


class SQLiteTransaction:
    def __init__(self, connection, store):
        self.connection = connection
        self.store = store
        self.write_owners = set()
        self.registry_history_cache = {}
        self.registry_prefix_cache = RegistryPrefixCache()

    def get(self, path: str) -> dict | None:
        if path.startswith(OWNERSHIP + "/"):
            row = self.connection.execute(
                "SELECT body FROM hub_account_ownership WHERE path = ?", (path,)
            ).fetchone()
        else:
            row = self.connection.execute(
                "SELECT body FROM hub_documents WHERE path = ?", (path,)
            ).fetchone()
        if row is None:
            return None
        try:
            value = strict_json_loads(row[0], max_bytes=MAX_STORED_DOCUMENT_BYTES)
        except ContractError:
            raise StoreUnavailable from None
        if type(value) is not dict:
            raise StoreUnavailable
        return _read_document(value, path=path)

    def get_many(self, paths, *, field_paths=None) -> dict[str, dict | None]:
        paths = _batch_paths(paths)
        field_paths = _batch_fields(field_paths)
        result = dict.fromkeys(paths)
        for start in range(0, len(paths), 128):
            group = paths[start : start + 128]
            placeholders = ",".join("?" for _ in group)
            rows = self.connection.execute(
                f"SELECT path, body FROM hub_documents WHERE path IN ({placeholders})", group
            ).fetchall()
            for path, body in rows:
                try:
                    value = strict_json_loads(body, max_bytes=MAX_STORED_DOCUMENT_BYTES)
                except ContractError:
                    raise StoreUnavailable from None
                if path not in result or type(value) is not dict:
                    raise StoreUnavailable
                result[path] = _read_document(_project(value, field_paths), path=path)
        return result

    def scan_owner(self, collection, field, owner, *, after=None, limit=4):
        from .source_erasure import SCANS as SOURCE_SCANS
        from .task_erasure import SCAN_FIELDS

        if (collection, field) not in SCAN_FIELDS.union(SOURCE_SCANS) or limit != 4:
            raise StoreUnavailable
        prefix = collection + "/"
        rows = self.connection.execute(
            "SELECT path, body FROM hub_documents WHERE path LIKE ? AND path > ? "
            "AND json_extract(body, ?) = ? ORDER BY path LIMIT ?",
            (prefix + "%", after or prefix, "$." + field, owner, limit),
        ).fetchall()
        try:
            return [
                (
                    path,
                    _read_document(
                        strict_json_loads(body, max_bytes=MAX_STORED_DOCUMENT_BYTES), path=path
                    ),
                )
                for path, body in rows
            ]
        except ContractError:
            raise StoreUnavailable from None

    def delete(self, path: str) -> None:
        _batch_paths((path,))
        self.connection.execute("DELETE FROM hub_documents WHERE path = ?", (path,))
        self.connection.execute(
            "DELETE FROM hub_account_ownership WHERE path = ?", (index_path(path),)
        )

    def put(self, path: str, value: dict) -> None:
        owners, index = plan_write(self, path, value)
        self.write_owners.update(owners)
        if index:
            self.connection.execute(
                "INSERT INTO hub_account_ownership(path, body) VALUES (?, ?) "
                "ON CONFLICT(path) DO UPDATE SET body = excluded.body",
                (index[0], canonical_json(index[1]).decode()),
            )
        self._put(path, value)

    def _put(self, path, value):
        data = stored_document(
            value, path=path, project=self.store.project, database=self.store.database
        )
        self.connection.execute(
            "INSERT INTO hub_documents(path, body) VALUES (?, ?) "
            "ON CONFLICT(path) DO UPDATE SET body = excluded.body",
            (path, canonical_json(data).decode()),
        )


class SQLiteHubStore:
    def __init__(self, path: str, *, project="local-hub", database="hub"):
        self.path = str(path)
        self.project = project
        self.database = database
        self._catalogue_fence_keys = FenceKeyHints()
        if self.path == ":memory:":
            raise ValueError("Use a private file for transactional local storage.")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(self.connect()) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS hub_documents "
                "(path TEXT PRIMARY KEY, body TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS hub_account_ownership "
                "(path TEXT PRIMARY KEY, body TEXT NOT NULL)"
            )
        Path(self.path).chmod(0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=4, isolation_level=None)

    def deleted_source_candidates(self, *, after):
        with closing(self.connect()) as connection:
            records = connection.execute(
                "SELECT path,body FROM hub_documents WHERE path LIKE 'hub_source_fences/%' "
                "AND path > ? AND json_extract(body,'$.state') = 'deleted' ORDER BY path LIMIT 32",
                (after or "hub_source_fences/",),
            )
            return [(path, strict_json_loads(body)) for path, body in records]

    def task_retention_candidates(self, status, *, after):
        if status not in {"trashed", "purged"}:
            raise StoreUnavailable
        with closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT path,json_extract(body,'$.definition') FROM hub_documents "
                "WHERE path LIKE 'hub_center_tasks/%' AND path > ? "
                "AND json_extract(body,'$.definition.status') = ? ORDER BY path LIMIT 32",
                (after or "hub_center_tasks/", status),
            )
            return [(path, strict_json_loads(definition)) for path, definition in rows]

    def transact(self, callback):
        with closing(self.connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                unit = SQLiteTransaction(connection, self)
                result = callback(unit)
                validate_writes(unit, unit.write_owners)
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise

    def read_snapshot(self, initial_paths, callback):
        from .snapshot_reads import sqlite_snapshot

        return sqlite_snapshot(self, initial_paths, callback)


class FirestoreTransaction:
    def __init__(self, transaction, store):
        self.transaction = transaction
        self.store = store
        self.pending = []
        self.write_owners = set()
        self.registry_history_cache = {}
        self.registry_prefix_cache = RegistryPrefixCache()
        # A transaction attempt has one snapshot. Reusing it does not cache an
        # authorization decision across requests or Firestore conflict retries.
        self._reads = {}
        self._read_bytes = 0

    def _remember(self, values, fields=None):
        for path, value in values.items():
            key = (path, fields)
            if key in self._reads or len(self._reads) >= 128:
                continue
            size = len(canonical_json(value))
            if self._read_bytes + size <= 8 * 1024 * 1024:
                self._reads[key] = copy.deepcopy(value)
                self._read_bytes += size

    def get(self, path: str) -> dict | None:
        if (path, None) in self._reads:
            return copy.deepcopy(self._reads[(path, None)])
        row = self.store.client.document(path).get(
            transaction=self.transaction, timeout=4, retry=None
        )
        value = None
        if row.exists:
            value = row.to_dict()
            if type(value) is not dict:
                raise StoreUnavailable
            value = _read_document(value, path=path)
        self._remember({path: value})
        return value

    def get_many(self, paths, *, field_paths=None) -> dict[str, dict | None]:
        paths = _batch_paths(paths)
        field_paths = _batch_fields(field_paths)
        fields = tuple(sorted(field_paths)) if field_paths is not None else None
        result = {path: copy.deepcopy(self._reads.get((path, fields))) for path in paths}
        missing = [path for path in paths if (path, fields) not in self._reads]
        for start in range(0, len(missing), 128):
            refs = [self.store.client.document(path) for path in missing[start : start + 128]]
            expected = {ref._document_path: ref.path for ref in refs}
            seen = set()
            for row in self.store.client.get_all(
                refs,
                field_paths=field_paths,
                transaction=self.transaction,
                timeout=4,
                retry=None,
            ):
                name = row.reference._document_path
                if name not in expected or name in seen:
                    raise StoreUnavailable
                seen.add(name)
                if not row.exists:
                    continue
                value = row.to_dict()
                if type(value) is not dict:
                    raise StoreUnavailable
                result[expected[name]] = _read_document(
                    _project(value, field_paths), path=expected[name]
                )
            if seen != set(expected):
                raise StoreUnavailable
        # Never retain a partial or malformed BatchGet response. Full documents
        # and projected rows occupy distinct entries; neither can impersonate
        # the other on a later read in this attempt.
        self._remember({path: result[path] for path in missing}, fields)
        return result

    def scan_owner(self, collection, field, owner, *, after=None, limit=4):
        from .source_erasure import SCANS as SOURCE_SCANS
        from .task_erasure import SCAN_FIELDS

        if (collection, field) not in SCAN_FIELDS.union(SOURCE_SCANS) or limit != 4:
            raise StoreUnavailable
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = (
            self.store.client.collection(collection)
            .where(filter=FieldFilter(field, "==", owner))
            .order_by("__name__")
            .limit(limit)
        )
        if after is not None:
            query = query.start_after({"__name__": self.store.client.document(after)})
        return [
            (row.reference.path, _read_document(row.to_dict(), path=row.reference.path))
            for row in query.stream(transaction=self.transaction, timeout=4, retry=None)
        ]

    def put(self, path: str, value: dict) -> None:
        owners, index = plan_write(self, path, value)
        self.write_owners.update(owners)
        if index:
            self._put(*index)
        self._put(path, value)

    def _put(self, path, value):
        data = stored_document(
            value, path=path, project=self.store.project, database=self.store.database
        )
        self.pending.append((path, _firestore_document(data, path=path)))

    def delete(self, path: str) -> None:
        _batch_paths((path,))
        self.pending.append((path, None))
        self.pending.append((index_path(path), None))

    def flush(self):
        validate_writes(self, self.write_owners)
        for path, data in self.pending:
            reference = self.store.client.document(path)
            if data is None:
                self.transaction.delete(reference)
            else:
                self.transaction.set(reference, data)


class FirestoreHubStore:
    def __init__(self, project: str, database: str, *, client=None):
        from google.cloud import firestore

        if not project or not database or database == "(default)":
            raise StoreUnavailable
        self.project = project
        self.database = database
        self._catalogue_fence_keys = FenceKeyHints()
        self.client = (
            client if client is not None else firestore.Client(project=project, database=database)
        )

    def deleted_source_candidates(self, *, after):
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = (
            self.client.collection("hub_source_fences")
            .where(filter=FieldFilter("state", "==", "deleted"))
            .order_by("__name__")
            .select(["ref", "ownerSubject"])
            .limit(32)
        )
        if after is not None:
            query = query.start_after({"__name__": self.client.document(after)})
        return [(r.reference.path, r.to_dict()) for r in query.stream(timeout=12, retry=None)]

    def task_retention_candidates(self, status, *, after):
        from google.cloud.firestore_v1.base_query import FieldFilter

        if status not in {"trashed", "purged"}:
            raise StoreUnavailable
        query = (
            self.client.collection("hub_center_tasks")
            .where(filter=FieldFilter("definition.status", "==", status))
            .order_by("__name__")
            .select(["definition"])
            .limit(32)
        )
        if after is not None:
            query = query.start_after({"__name__": self.client.document(after)})
        return [
            (row.reference.path, row.to_dict()["definition"])
            for row in query.stream(timeout=12, retry=None)
        ]

    def transact(self, callback):
        from google.cloud import firestore

        from folioview_shared.firestore import BoundedTransaction

        @firestore.transactional
        def run(transaction):
            unit = FirestoreTransaction(transaction, self)
            result = callback(unit)
            unit.flush()
            return result

        return run(BoundedTransaction(self.client, max_attempts=3))

    def read_snapshot(self, initial_paths, callback):
        from .snapshot_reads import firestore_snapshot

        return firestore_snapshot(self, initial_paths, callback)


@lru_cache(maxsize=1)
def get_store():
    """Load only for authenticated private requests, never process health."""
    cloud = "K_SERVICE" in os.environ
    backend = os.getenv("AGENT_HUB_STORE_BACKEND", "firestore" if cloud else "sqlite")
    if cloud and (backend != "firestore" or "FIRESTORE_EMULATOR_HOST" in os.environ):
        raise StoreUnavailable
    if backend == "firestore":
        return FirestoreHubStore(
            os.getenv("FIREBASE_PROJECT_ID", "").strip(),
            os.getenv("FIRESTORE_DATABASE", "").strip(),
        )
    if backend == "sqlite":
        return SQLiteHubStore(
            os.getenv("AGENT_HUB_DB_PATH", "/tmp/folioview/agent-hub.sqlite3"),
        )
    raise StoreUnavailable
