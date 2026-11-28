"""Immutable verified registry entries and bounded, fixed-target recovery pages."""

import hashlib
import time
from typing import Literal

from google.cloud import firestore

from folioview_shared.encrypted.authority import RegistryCertificateMemo, verify_registry
from folioview_shared.encrypted.constants import CONTRACT_VERSION, MAX_REGISTRY_BYTES
from folioview_shared.encrypted.crypto import verify_jws
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json, strict_json_loads
from folioview_shared.encrypted.private_resources import (
    MAX_REGISTRY_PAGE_BYTES,
    PrivateRegistryCursor,
)
from folioview_shared.encrypted.schema import validate_schema
from folioview_shared.firestore import BoundedTransaction
from folioview_shared.identity import owner_key

from ..firestore_reads import read_documents
from ..resources import FirestoreUserResourceStore, ResourceUnavailable, SQLiteUserResourceStore
from .recovery import ClosedModel, Identifier, RecoveryHeads, RegistryHead

PROFILE = "folioview.owner-registry-page.v1"
ORIGINAL_HEAD_PROFILE = "folioview.owner-original-registry-head.v1"
COLLECTION = "user_private_registry_history"
MAX_ENTRY_BYTES = MAX_REGISTRY_BYTES + 1024
MAX_PAGE_ENTRIES = 4
HISTORY_READ_BATCH_SIZE = 12


class RegistryPageRequest(ClosedModel):
    contractVersion: Literal[CONTRACT_VERSION]
    profile: Literal[PROFILE]
    ownerSubject: Identifier
    vaultId: Identifier
    base: RegistryHead | None
    target: RegistryHead


class OriginalRegistryHeadRequest(ClosedModel):
    contractVersion: Literal[CONTRACT_VERSION]
    profile: Literal[ORIGINAL_HEAD_PROFILE]
    ownerSubject: Identifier
    vaultId: Identifier
    target: RegistryHead


def _index(owner, vault, epoch, sequence):
    return hashlib.sha256(canonical_json([owner, vault, epoch, sequence])).hexdigest()


class RegistryHistory:
    def __init__(self, heads: RecoveryHeads):
        self.heads = heads
        self.store = heads.store

    def _collection(self):
        if not isinstance(self.store, FirestoreUserResourceStore):
            raise ContractError("authorization_unavailable")
        return self.store.client.collection(COLLECTION)

    @staticmethod
    def _entry(raw, sequence, scope, memo):
        if not isinstance(raw, (str, bytes)):
            raise ContractError("authorization_unavailable")
        try:
            value = strict_json_loads(raw, max_bytes=MAX_ENTRY_BYTES)
            if type(value) is not dict or value.keys() != {"head", "bundle", "rootJwk"}:
                raise ValueError
            head = RegistryHead.model_validate(value["head"]).model_dump()
            if head["registrySequence"] != sequence:
                raise ValueError
            registry = verify_registry(
                value["bundle"],
                root_jwk=value["rootJwk"],
                pinned_root_key_id=scope["rootKeyId"],
                owner_subject=scope["ownerSubject"],
                vault_id=scope["vaultId"],
                now=int(time.time()),
                signature_memo=memo,
            )
            if PrivateRegistryCursor(registry, head["registryEpoch"]).head() != head:
                raise ValueError
            return value
        except (ContractError, ValueError):
            raise ContractError("authorization_unavailable") from None

    def stage(self, bundle: dict, *, root_jwk: dict, cursor: PrivateRegistryCursor):
        """Stage a bundle after its complete chain or signed transition is verified."""
        registry = cursor.registry
        validate_schema("PublicJWK", root_jwk)
        verified = verify_registry(
            bundle,
            root_jwk=root_jwk,
            pinned_root_key_id=registry.root_key_id,
            owner_subject=registry.owner_subject,
            vault_id=registry.vault_id,
            root_epoch=registry.root_epoch,
            now=registry.issued_at,
        )
        if PrivateRegistryCursor(verified, cursor.registry_epoch).head() != cursor.head():
            raise ContractError("registry_conflict")
        key = _index(
            registry.owner_subject,
            registry.vault_id,
            cursor.registry_epoch,
            registry.registry_sequence,
        )
        body = canonical_json({"head": cursor.head(), "bundle": bundle, "rootJwk": root_jwk})
        if len(body) > MAX_ENTRY_BYTES:
            raise ContractError("payload_too_large")
        if isinstance(self.store, SQLiteUserResourceStore):
            with self.store.connection() as db:
                db.execute(
                    f"CREATE TABLE IF NOT EXISTS {COLLECTION} "
                    "(entry TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                db.execute("BEGIN IMMEDIATE")
                previous = db.execute(
                    f"SELECT value FROM {COLLECTION} WHERE entry=?", (key,)
                ).fetchone()
                identical = previous is None or previous[0] == body.decode()
                if previous is None:
                    db.execute(
                        f"INSERT INTO {COLLECTION}(entry,value) VALUES (?,?)", (key, body.decode())
                    )
            if not identical:
                raise ContractError("registry_conflict")
            return

        reference = self._collection().document(key)

        @firestore.transactional
        def write(transaction):
            current = reference.get(transaction=transaction, timeout=4, retry=None)
            if not current.exists:
                transaction.set(reference, {"entry": body})
            elif current.to_dict() != {"entry": body}:
                raise ContractError("registry_conflict")

        write(BoundedTransaction(self.store.client, max_attempts=2))

    def _read(self, scope, epoch, sequences, *, memo=None):
        keys = [_index(scope["ownerSubject"], scope["vaultId"], epoch, n) for n in sequences]
        if isinstance(self.store, SQLiteUserResourceStore):
            placeholders = ", ".join("?" for _ in keys)
            try:
                with self.store.connection() as db:
                    found = dict(
                        db.execute(
                            f"SELECT entry,value FROM {COLLECTION} WHERE entry IN ({placeholders})",
                            keys,
                        )
                    )
            except ResourceUnavailable:
                raise ContractError("authorization_unavailable") from None
            values = [found.get(key) for key in keys]
        else:
            collection = self._collection()
            docs = read_documents(
                self.store.client,
                None,
                [collection.document(key) for key in keys],
                maximum=HISTORY_READ_BATCH_SIZE,
            )
            values = [
                doc["entry"] if type(doc) is dict and doc.keys() == {"entry"} else None
                for doc in docs
            ]
        if memo is None:
            memo = RegistryCertificateMemo()
        return [
            self._entry(raw, sequence, scope, memo)
            for raw, sequence in zip(values, sequences, strict=True)
        ]

    def _require_original_target(self, uid, vault, head, target):
        if (
            head.get("handover") is None
            or head["archive"]["state"] != "active"
            or target["registryEpoch"] != 1
            or (head["registryStart"] or {}).get("registryEpoch") != 2
        ):
            raise ContractError("registry_conflict")
        from .authority_cutover import UserAuthorityCutover

        proof = UserAuthorityCutover(self.store).read_start(
            uid, vault, "original_registry_target_page", now=int(time.time())
        )
        if (
            proof["rootKeyId"] != head["rootKeyId"]
            or proof["registryStart"] != head["registryStart"]
            or proof["archive"] != head["archive"]
        ):
            raise ContractError("registry_conflict")
        transition = verify_jws(
            proof["signedTransition"],
            proof["rootJwk"],
            typ="fv-control+jws",
            expected_kid=head["rootKeyId"],
        )
        if transition["previousHead"] != target:
            raise ContractError("registry_conflict")

    def page(self, uid: str, vault: str, request: RegistryPageRequest):
        owner = owner_key(uid)
        if request.ownerSubject != owner or request.vaultId != vault:
            raise ContractError("not_found")
        head = self.heads.read(owner)
        if head is None or head["ownerSubject"] != owner or head["vaultId"] != vault:
            raise ContractError("not_found")
        target = request.target.model_dump()
        if target != head["registry"]:
            self._require_original_target(uid, vault, head, target)
        epoch = request.target.registryEpoch
        base = request.base
        if (base is None and epoch != 1) or (
            base is not None
            and (
                base.registryEpoch != epoch
                or base.registrySequence >= request.target.registrySequence
            )
        ):
            raise ContractError("registry_conflict")
        start = 1 if base is None else base.registrySequence + 1
        tail = min(
            request.target.registrySequence, start + MAX_PAGE_ENTRIES - 1 - int(base is not None)
        )
        sequences = list(range(start, tail + 1))
        if base is not None:
            sequences.insert(0, base.registrySequence)
        entries = self._read(head, epoch, sequences)
        if base is not None and entries.pop(0)["head"] != base.model_dump():
            raise ContractError("registry_conflict")

        page = {
            "contractVersion": CONTRACT_VERSION,
            "profile": PROFILE,
            "ownerSubject": owner,
            "vaultId": vault,
            "rootKeyId": head["rootKeyId"],
            "base": base.model_dump() if base is not None else None,
            "target": target,
            "bundles": [],
        }
        for entry in entries:
            current = entry["head"]
            if (
                current["registryEpoch"] != epoch
                or current["keyEpoch"] > request.target.keyEpoch
                or (
                    current["registrySequence"] == request.target.registrySequence
                    and current != target
                )
            ):
                raise ContractError("authorization_unavailable")
            page["bundles"].append(entry["bundle"])
            if len(canonical_json(page)) > MAX_REGISTRY_PAGE_BYTES:
                page["bundles"].pop()
                break
        if not page["bundles"]:
            raise ContractError("payload_too_large")
        return page

    def original_head(self, uid: str, vault: str, request: OriginalRegistryHeadRequest):
        owner = owner_key(uid)
        if request.ownerSubject != owner or request.vaultId != vault:
            raise ContractError("not_found")
        head = self.heads.read(owner)
        if head is None or head["ownerSubject"] != owner or head["vaultId"] != vault:
            raise ContractError("not_found")
        target = request.target.model_dump()
        self._require_original_target(uid, vault, head, target)
        [entry] = self._read(head, 1, [request.target.registrySequence])
        if entry["head"] != target:
            raise ContractError("registry_conflict")
        return {
            "contractVersion": CONTRACT_VERSION,
            "profile": ORIGINAL_HEAD_PROFILE,
            "ownerSubject": owner,
            "vaultId": vault,
            "rootKeyId": head["rootKeyId"],
            "target": target,
            "bundle": entry["bundle"],
        }
