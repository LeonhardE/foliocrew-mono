"""Immutable User-side baselines for migration of an existing encrypted vault."""

import hashlib
import re

from google.cloud import firestore

from folioview_shared.encrypted.authority import RegistryCertificateMemo, verify_registry
from folioview_shared.encrypted.constants import MAX_SAFE_INTEGER
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json, strict_json_loads
from folioview_shared.encrypted.legacy_archive import verify_legacy_archive_history
from folioview_shared.encrypted.private_resources import PrivateRegistryCursor
from folioview_shared.encrypted.schema import validate_schema
from folioview_shared.firestore import BoundedTransaction

from ..resources import FirestoreUserResourceStore, ResourceUnavailable, SQLiteUserResourceStore

COLLECTION = "user_private_vault_baselines"
MAX_BASELINE_BYTES = 520_000
_VAULT_FIELDS = {
    "ownerSubject",
    "vaultId",
    "rootKeyId",
    "rootJwk",
    "version",
    "operationCount",
    "archive",
    "sources",
    "registryHistory",
}
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _scope(owner, vault):
    if (
        type(owner) is not str
        or not _DIGEST.fullmatch(owner)
        or type(vault) is not str
        or not _ID.fullmatch(vault)
    ):
        raise ContractError("recipient_binding_mismatch")


def verified_baseline(owner, vault, lifecycle, *, now):
    """Verify original history and keep the separately staged registry anchored by its head."""
    if (
        type(vault) is not dict
        or vault.keys() not in (_VAULT_FIELDS, _VAULT_FIELDS | {"retiredSourceCount"})
        or vault["ownerSubject"] != owner
    ):
        raise ContractError("recipient_binding_mismatch")
    _scope(owner, vault["vaultId"])
    history, sources = vault["registryHistory"], vault["sources"]
    retired = vault.get("retiredSourceCount", 0)
    if (
        type(history) is not list
        or not 1 <= len(history) <= 32
        or type(sources) is not list
        or len(sources) > 10
        or type(vault["version"]) is not int
        or type(vault["operationCount"]) is not int
        or vault["version"] != vault["operationCount"]
        or vault["version"] > MAX_SAFE_INTEGER
        or type(retired) is not int
        or retired < 0
        or vault["version"] != len(history) + len(sources) + retired
    ):
        raise ContractError("malformed_request")
    resource_ids = set()
    for item in sources:
        if (
            type(item) is not dict
            or item.keys() != {"resourceRef", "sourceEpoch"}
            or (type(item["sourceEpoch"]) is not int or item["sourceEpoch"] != 1)
        ):
            raise ContractError("malformed_request")
        ref = item["resourceRef"]
        validate_schema("ResourceRef", ref)
        if (
            ref["kind"] != "holdings"
            or ref["sourceService"] != "portfolio"
            or ref["resourceId"] in resource_ids
        ):
            raise ContractError("malformed_request")
        resource_ids.add(ref["resourceId"])

    registry = None
    memo = RegistryCertificateMemo()
    for sequence, bundle in enumerate(history, start=1):
        registry = verify_registry(
            bundle,
            root_jwk=vault["rootJwk"],
            pinned_root_key_id=vault["rootKeyId"],
            owner_subject=owner,
            vault_id=vault["vaultId"],
            now=now,
            previous=registry,
            signature_memo=memo,
        )
        if registry.registry_sequence != sequence or (sequence == 1 and registry.key_epoch != 1):
            raise ContractError("registry_conflict")
    state = verify_legacy_archive_history(vault, registry, lifecycle)
    # The source anchors in the original vault refer to creation only. Live source
    # fences and current projections are separate stores with their own authority.
    value = {key: value for key, value in vault.items() if key != "registryHistory"}
    value.update(
        {
            "registry": PrivateRegistryCursor(registry, 1).head(),
            "archiveLifecycle": lifecycle,
            "archiveBoundary": {
                "state": "deleted" if state["deleted"] else "active",
                "version": state["version"] + 1,
                "digest": state["digest"],
            },
        }
    )
    encoded = canonical_json(value)
    if len(encoded) > MAX_BASELINE_BYTES:
        raise ContractError("payload_too_large")
    return encoded


class LegacyVaultBaselines:
    """Copy reviewed ciphertext and original lifecycle receipts without publishing authority."""

    def __init__(self, store):
        self.store = store
        if isinstance(store, SQLiteUserResourceStore):
            with store.connection() as db:
                db.execute(
                    f"CREATE TABLE IF NOT EXISTS {COLLECTION} "
                    "(key TEXT PRIMARY KEY, body BLOB NOT NULL)"
                )

    @staticmethod
    def _key(owner, vault, digest):
        _scope(owner, vault)
        if type(digest) is not str or not _DIGEST.fullmatch(digest):
            raise ContractError("malformed_request")
        return _sha(canonical_json([owner, vault, digest]))

    def _collection(self):
        if (
            not isinstance(self.store, FirestoreUserResourceStore)
            or self.store.client._database != "user-data"
        ):
            raise ContractError("authorization_unavailable")
        return self.store.client.collection(COLLECTION)

    def _reference(self, key):
        return self._collection().document(key)

    @staticmethod
    def _read_local(db, key):
        value = db.execute(f"SELECT body FROM {COLLECTION} WHERE key=?", (key,)).fetchone()
        return value[0] if value else None

    @staticmethod
    def _read_firestore(reference, transaction=None):
        snapshot = reference.get(transaction=transaction, timeout=4, retry=None)
        if not snapshot.exists:
            return None
        row = snapshot.to_dict()
        if type(row) is not dict or row.keys() != {"body"} or type(row["body"]) is not bytes:
            raise ContractError("authorization_unavailable")
        return row["body"]

    def stage(self, owner, vault, lifecycle, *, expected_digest, now):
        prepared = verified_baseline(owner, vault, lifecycle, now=now)
        return self._stage_bytes(owner, vault["vaultId"], prepared, expected_digest, archive=True)

    def stage_original_operations(self, owner, vault, records, *, expected_digest):
        from .original_operations import original_operation_baseline

        prepared = original_operation_baseline(owner, vault, records)
        return self._stage_bytes(owner, vault["vaultId"], prepared, expected_digest)

    def _stage_bytes(self, owner, vault, prepared, expected_digest, *, archive=False):
        from .authority_cutover import ARCHIVE_RECORDS

        if _sha(prepared) != expected_digest:
            raise ContractError("version_conflict")
        key = self._key(owner, vault, expected_digest)

        def check(previous):
            if previous not in (None, prepared):
                raise ContractError("version_conflict")
            return previous is None

        if isinstance(self.store, SQLiteUserResourceStore):
            try:
                with self.store.connection() as db:
                    db.execute("BEGIN IMMEDIATE")
                    if not check(self._read_local(db, key)):
                        return False
                    if (
                        archive
                        and db.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                            (ARCHIVE_RECORDS,),
                        ).fetchone()
                        and db.execute(
                            f"SELECT 1 FROM {ARCHIVE_RECORDS} WHERE owner=?", (owner,)
                        ).fetchone()
                    ):
                        raise ContractError("version_conflict")
                    db.execute(f"INSERT INTO {COLLECTION} VALUES (?, ?)", (key, prepared))
            except ResourceUnavailable as error:
                if isinstance(error.__cause__, ContractError):
                    raise error.__cause__ from None
                raise ContractError("authorization_unavailable") from None
            return True

        reference = self._reference(key)

        @firestore.transactional
        def write(transaction):
            if not check(self._read_firestore(reference, transaction)):
                return False
            if archive:
                active = self.store.client.collection(ARCHIVE_RECORDS).document(owner)
                if active.get(
                    field_paths=[], transaction=transaction, timeout=4, retry=None
                ).exists:
                    raise ContractError("version_conflict")
            transaction.create(reference, {"body": prepared})
            return True

        return write(BoundedTransaction(self.store.client, max_attempts=2))

    def erase_archives(self, owner, vault, root, *, apply=True):
        """Remove every staged archive for this exact transfer."""
        _scope(owner, vault)

        def matches(key, raw):
            data = strict_json_loads(raw, max_bytes=MAX_BASELINE_BYTES)
            if (data.get("ownerSubject"), data.get("vaultId"), data.get("rootKeyId")) != (
                owner,
                vault,
                root,
            ):
                return False
            if key != self._key(owner, vault, _sha(raw)):
                raise ContractError("authorization_unavailable")
            # Original operations contain only per-command proofs. The separately staged vault
            # snapshots hold the actual credential identifier, salt and wrapped key envelope.
            return data.get("archive") is not None

        if isinstance(self.store, SQLiteUserResourceStore):
            with self.store.connection() as db:
                db.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
                keys = [
                    key
                    for key, raw in db.execute(f"SELECT key,body FROM {COLLECTION}")
                    if matches(key, raw)
                ]
                if apply:
                    db.executemany(
                        f"DELETE FROM {COLLECTION} WHERE key=?", [(key,) for key in keys]
                    )
                return len(keys)

        query = self._collection().select(["body"]).order_by("__name__").limit(64)

        def inventory():
            cursor = None
            while True:
                page = query.start_after(cursor) if cursor else query
                rows = list(page.stream(timeout=15))
                for row in rows:
                    if matches(row.id, row.get("body")):
                        yield row.reference, row.update_time
                if len(rows) < 64:
                    break
                cursor = rows[-1]

        keys = list(inventory())
        if apply:
            for start in range(0, len(keys), 100):
                batch = self.store.client.batch()
                for ref, updated in keys[start : start + 100]:
                    batch.delete(
                        ref, option=self.store.client.write_option(last_update_time=updated)
                    )
                batch.commit(timeout=10)
            if keys and next(inventory(), None) is not None:
                raise ContractError("authorization_unavailable")
        return len(keys)

    def read(self, owner, vault, digest):
        key = self._key(owner, vault, digest)
        if isinstance(self.store, SQLiteUserResourceStore):
            with self.store.connection() as db:
                raw = self._read_local(db, key)
        else:
            raw = self._read_firestore(self._reference(key))
        if raw is None:
            return None
        if type(raw) is not bytes or len(raw) > MAX_BASELINE_BYTES or _sha(raw) != digest:
            raise ContractError("authorization_unavailable")
        stored = strict_json_loads(raw, max_bytes=MAX_BASELINE_BYTES)
        if (
            type(stored) is not dict
            or stored.get("ownerSubject") != owner
            or stored.get("vaultId") != vault
        ):
            raise ContractError("recipient_binding_mismatch")
        return raw
