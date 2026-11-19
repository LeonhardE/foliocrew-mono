"""Signed owner holdings registrations under the transferred User registry."""

import secrets
import time

from google.cloud import firestore
from pydantic import ValidationError

from folioview_shared.encrypted.authority import (
    RegistryCertificateMemo,
    verify_control_command,
    verify_registry,
)
from folioview_shared.encrypted.constants import CONTRACT_VERSION, MAX_RESOURCES, MAX_SAFE_INTEGER
from folioview_shared.encrypted.crypto import _signed_parts, signing_input_fingerprint
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json
from folioview_shared.encrypted.private_resources import (
    PrivateRegistryCursor,
    source_index_digest,
    verify_private_registry_transition,
)
from folioview_shared.encrypted.schema import validate_schema
from folioview_shared.firestore import BoundedTransaction
from folioview_shared.identity import owner_key

from ..firestore_reads import read_documents
from ..resources import ResourceUnavailable, SQLiteUserResourceStore
from .authority_cutover import UserAuthorityCutover
from .legacy_baselines import _sha
from .recovery import COLLECTION as HEADS
from .recovery import RecoveryHeads
from .registry_pages import MAX_PAGE_ENTRIES
from .report_sources import HOLDINGS_FENCES, holdings_fence_key
from .source_invalidations import SOURCE_INDEX

SOURCE_REGISTRATIONS = "user_private_source_registration_receipts"
_MAX_REGISTRY_EXTENSION = 128


def current_registry(cutover, uid, vault, now):
    """Build authority only to the fixed current head returned by User."""
    evidence = cutover.read_start(uid, vault, secrets.token_urlsafe(24), now=now)
    scope = {key: evidence[key] for key in ("ownerSubject", "vaultId", "rootKeyId")}
    root = evidence["rootJwk"]
    target = evidence["registry"]
    start = verify_private_registry_transition(
        evidence["signedTransition"],
        first_bundle=evidence["firstBundle"],
        root_jwk=root,
        owner_subject=scope["ownerSubject"],
        vault_id=vault,
        pinned_root_key_id=scope["rootKeyId"],
        authenticated_start=evidence["registryStart"],
        previous=None,
        now=now,
    )
    registry = start.registry
    current = start.head()
    if target["registryEpoch"] != start.registry_epoch or not (
        0 <= target["registrySequence"] - current["registrySequence"] <= _MAX_REGISTRY_EXTENSION
    ):
        raise ContractError("registry_conflict")
    memo = RegistryCertificateMemo()
    tail = target["registrySequence"]
    for first in range(current["registrySequence"] + 1, tail + 1, MAX_PAGE_ENTRIES):
        sequences = range(first, min(tail + 1, first + MAX_PAGE_ENTRIES))
        entries = cutover.verifier.history._read(scope, start.registry_epoch, list(sequences))
        for sequence, entry in zip(sequences, entries, strict=True):
            registry = verify_registry(
                entry["bundle"],
                root_jwk=root,
                pinned_root_key_id=scope["rootKeyId"],
                owner_subject=scope["ownerSubject"],
                vault_id=vault,
                previous=registry,
                now=now,
                signature_memo=memo,
            )
            if registry.registry_sequence != sequence:
                raise ContractError("registry_conflict")
    if PrivateRegistryCursor(registry, start.registry_epoch).head() != target:
        raise ContractError("registry_conflict")
    return evidence, registry


def _matches_current(head, sample):
    return (
        head is not None
        and head.get("handover") is not None
        and all(
            head[key] == sample[key]
            for key in (
                "ownerSubject",
                "vaultId",
                "rootKeyId",
                "vaultVersion",
                "archive",
                "registry",
                "registryStart",
            )
        )
    )


def _replay(saved, owner, vault, source, operation, fingerprint):
    if type(saved) is not dict or saved.keys() != {
        "ownerSubject",
        "vaultId",
        "sourceId",
        "operationId",
        "fingerprint",
        "result",
    }:
        raise ContractError("authorization_unavailable")
    if (saved["ownerSubject"], saved["vaultId"], saved["sourceId"], saved["operationId"]) != (
        owner,
        vault,
        source,
        operation,
    ) or saved["fingerprint"] != fingerprint:
        raise ContractError("idempotency_conflict")
    return saved["result"]


class HoldingsRegistrations:
    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock
        self.authority = UserAuthorityCutover(store)
        self.heads = RecoveryHeads(store)
        if isinstance(store, SQLiteUserResourceStore):
            with store.connection() as db:
                db.execute(
                    f"CREATE TABLE IF NOT EXISTS {SOURCE_REGISTRATIONS} "
                    "(owner TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )

    def register(self, uid, vault, source, signed, operation):
        for value in (vault, source):
            validate_schema("Identifier", value)
        validate_schema("OperationIdentifier", operation)
        validate_schema("SignedObject", signed)
        fingerprint = signing_input_fingerprint(signed)
        # Parse the bounded command before performing the current registry read.
        _, payload = _signed_parts(signed)
        if payload.get("stableOperationId") != operation:
            raise ContractError("recipient_binding_mismatch")
        owner = owner_key(uid)
        key = _sha(canonical_json([owner, "source", operation]))
        stamp = (owner, vault, source, operation, fingerprint)
        self.authority._named_store()
        try:
            saved = self.authority._read(((SOURCE_REGISTRATIONS, key),))[0]
            if saved is not None:
                return _replay(saved, *stamp)
            now = int(self.clock())
            sample, registry = current_registry(self.authority, uid, vault, now)
            verify_control_command(
                signed,
                registry=registry,
                expected_action="manual_source_create",
                expected_target_id=source,
                expected_version=0,
                expected_source_epoch=None,
                expected_parameters={},
                now=now,
            )
            ref = {
                "kind": "holdings",
                "sourceService": "portfolio",
                "resourceId": source,
                "incarnation": "inc_" + fingerprint[:32],
            }
            fence_id = holdings_fence_key(owner, vault, source)
            result = {
                "contractVersion": CONTRACT_VERSION,
                "source": {"resourceRef": ref, "sourceEpoch": 1},
            }
            receipt = {
                "ownerSubject": owner,
                "vaultId": vault,
                "sourceId": source,
                "operationId": operation,
                "fingerprint": fingerprint,
                "result": result,
            }

            def commit(head, index, fence, existing):
                if existing is not None:
                    return _replay(existing, *stamp), None
                if not _matches_current(head, sample) or head["vaultVersion"] >= MAX_SAFE_INTEGER:
                    raise ContractError("version_conflict")
                if (
                    type(index) is not dict
                    or index.keys() != {"ownerSubject", "vaultId", "entries"}
                    or (index["ownerSubject"], index["vaultId"]) != (owner, vault)
                    or source_index_digest(index["entries"]) != head["sourcesDigest"]
                ):
                    raise ContractError("source_unavailable")
                if (
                    fence is not None
                    or sum(
                        item["binding"]["ref"]["kind"] == "holdings" for item in index["entries"]
                    )
                    >= MAX_RESOURCES
                ):
                    raise ContractError("version_conflict")
                binding = {"ref": ref, "sourceEpoch": 1}
                entries = [*index["entries"], {"binding": binding, "state": "active"}]
                return result, (
                    {
                        **head,
                        "vaultVersion": head["vaultVersion"] + 1,
                        "sourcesDigest": source_index_digest(entries),
                    },
                    {**index, "entries": entries},
                    {
                        "ownerSubject": owner,
                        "vaultId": vault,
                        "binding": binding,
                        "state": "eligible",
                        "currentRevision": 0,
                    },
                    receipt,
                )

            return self._write(owner, fence_id, key, commit)
        except ContractError:
            raise
        except ResourceUnavailable as error:
            if isinstance(error.__cause__, ContractError):
                raise error.__cause__ from None
            raise ContractError("authorization_unavailable") from None
        except (ValidationError, ValueError, TypeError, OverflowError):
            raise ContractError("authorization_unavailable") from None

    def _write(self, owner, fence, key, commit):
        cells = (
            (HEADS, owner),
            (SOURCE_INDEX, owner),
            (HOLDINGS_FENCES, fence),
            (SOURCE_REGISTRATIONS, key),
        )
        if isinstance(self.store, SQLiteUserResourceStore):
            with self.store.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                result, changed = commit(*self.authority._read_sqlite(db, cells))
                if changed is not None:
                    for position, ((table, identity), value) in enumerate(
                        zip(cells, changed, strict=True)
                    ):
                        sql = (
                            f"UPDATE {table} SET value=? WHERE owner=?"
                            if position < 2
                            else f"INSERT INTO {table}(value,owner) VALUES (?,?)"
                        )
                        db.execute(sql, (canonical_json(value).decode(), identity))
                return result

        refs = self.authority._references(cells)

        @firestore.transactional
        def write(transaction):
            raw_head, index, state, previous = read_documents(self.store.client, transaction, refs)
            head = None
            if raw_head is not None:
                if raw_head.keys() != {"view"} or type(raw_head["view"]) is not bytes:
                    raise ContractError("authorization_unavailable")
                head = self.heads._decode(raw_head["view"])
            result, changed = commit(head, index, state, previous)
            if changed is not None:
                live, updated, source, receipt = changed
                transaction.set(refs[0], {"view": canonical_json(live)})
                transaction.set(refs[1], updated)
                transaction.create(refs[2], source)
                transaction.create(refs[3], receipt)
            return result

        return write(BoundedTransaction(self.store.client, max_attempts=3))
