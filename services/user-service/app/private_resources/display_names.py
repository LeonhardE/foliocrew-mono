"""Encrypted Owner aliases in the same User authority as their holdings sources."""

import time

from pydantic import ValidationError

from folioview_shared.encrypted.budgets import check_read_response
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import _signed_parts, signing_input_fingerprint
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json
from folioview_shared.encrypted.private_display_names import (
    DISPLAY_NAME_PROFILE,
    check_display_name_replay,
    plan_display_name_update,
    validate_display_name_envelope,
    validate_display_name_schema,
    validate_display_name_state,
)
from folioview_shared.encrypted.private_resources import source_index_digest
from folioview_shared.identity import owner_key

from ..resources import ResourceUnavailable, SQLiteUserResourceStore
from .authority_cutover import UserAuthorityCutover
from .display_name_cleanup import NAMES, OPERATIONS
from .legacy_baselines import _sha
from .recovery import COLLECTION as HEADS
from .recovery import CurrentHead
from .report_sources import HOLDINGS_FENCES, HoldingsFence, holdings_fence_key
from .source_invalidations import SOURCE_INDEX
from .source_registrations import _matches_current, current_registry


def _context(owner, vault, root, ref):
    return {"ownerSubject": owner, "vaultId": vault, "rootKeyId": root, "ref": ref}


def _path(context, operation=None):
    ident = _sha(canonical_json(context))
    return (
        (NAMES, ident)
        if operation is None
        else (OPERATIONS, _sha(canonical_json([ident, operation])))
    )


def _item(value, context):
    if value is None:
        return None
    if type(value) is not dict or value.keys() != {"state", "command"}:
        raise ContractError("authorization_unavailable")
    _, payload = _signed_parts(value["command"])
    payload = validate_display_name_schema("DisplayNameControl", payload)
    if any(payload[key] != expected for key, expected in context.items()):
        raise ContractError("authorization_unavailable")
    state = validate_display_name_state(value["state"], context=payload)
    if (
        any(
            state[key] != payload[key]
            for key in ("revision", "recipientKeyId", "stableOperationId")
        )
        or state["operationFingerprint"] != signing_input_fingerprint(value["command"])
        or payload["revision"] != payload["expectedRevision"] + 1
        or not payload["issuedAt"] <= state["acceptedAt"] <= payload["issuedAt"] + 300
    ):
        raise ContractError("authorization_unavailable")
    validate_display_name_envelope(payload["envelope"], context=payload)
    return value


def _response(**fields):
    value = {"contractVersion": CONTRACT_VERSION, "profile": DISPLAY_NAME_PROFILE, **fields}
    check_read_response(value)
    return value


class PrivateDisplayNames:
    def __init__(self, store, *, clock=time.time):
        self.cutover = UserAuthorityCutover(store)
        self.cutover._named_store()
        self.clock = clock
        if isinstance(store, SQLiteUserResourceStore):
            with store.connection() as db:
                for table in (NAMES, OPERATIONS):
                    db.execute(
                        f"CREATE TABLE IF NOT EXISTS {table} "
                        "(owner TEXT PRIMARY KEY, value TEXT NOT NULL)"
                    )

    @staticmethod
    def _head(read, owner, vault):
        raw, index = read(((HEADS, owner), (SOURCE_INDEX, owner)))
        if raw is None:
            raise ContractError("not_found")
        head = CurrentHead.model_validate(raw)
        if (
            (head.ownerSubject, head.vaultId) != (owner, vault)
            or head.handover is None
            or head.archive.state != "active"
        ):
            raise ContractError("not_found")
        if (
            type(index) is not dict
            or index.keys() != {"ownerSubject", "vaultId", "entries"}
            or (index["ownerSubject"], index["vaultId"]) != (owner, vault)
            or source_index_digest(index["entries"]) != head.sourcesDigest
        ):
            raise ContractError("authorization_unavailable")
        return raw, head.rootKeyId, index["entries"]

    def read(self, uid, vault, source, operation):
        owner = owner_key(uid)

        def snapshot(read, _write):
            _, root, entries = self._head(read, owner, vault)
            if source is None:
                contexts = [
                    _context(owner, vault, root, row["binding"]["ref"])
                    for row in entries
                    if row["state"] == "active" and row["binding"]["ref"]["kind"] == "holdings"
                ]
                items = (
                    (
                        _item(raw, context)
                        for raw, context in zip(
                            read(tuple(map(_path, contexts))), contexts, strict=True
                        )
                    )
                    if contexts
                    else ()
                )
                return _response(items=[item for item in items if item is not None])
            current = next(
                (
                    row
                    for row in entries
                    if row["binding"]["ref"]["kind"] == "holdings"
                    and row["binding"]["ref"]["resourceId"] == source
                ),
                None,
            )
            if operation is None:
                if current is None or current["state"] != "active":
                    raise ContractError("not_found")
                ref = current["binding"]["ref"]
            else:
                row = read(((HOLDINGS_FENCES, holdings_fence_key(owner, vault, source)),))[0]
                if row is None:
                    raise ContractError("not_found")
                fence = HoldingsFence.model_validate(row)
                if fence.state == "deleted":
                    raise ContractError("not_found")
                ref = fence.binding.model_dump()["ref"]
                if (fence.ownerSubject, fence.vaultId, ref["resourceId"]) != (owner, vault, source):
                    raise ContractError("authorization_unavailable")
            context = _context(owner, vault, root, ref)
            item = _item(read((_path(context, operation),))[0], context)
            if operation is not None:
                if item is None:
                    raise ContractError("not_found")
                if item["state"]["stableOperationId"] != operation:
                    raise ContractError("authorization_unavailable")
            return _response(item=item)

        try:
            return self.cutover._transaction(snapshot, writes=False)
        except ResourceUnavailable as error:
            if isinstance(error.__cause__, ContractError):
                raise error.__cause__ from None
            raise ContractError("authorization_unavailable") from None
        except ValidationError:
            raise ContractError("authorization_unavailable") from None

    def write(self, uid, vault, source, operation, signed):
        owner = owner_key(uid)
        _, payload = _signed_parts(signed)
        payload = validate_display_name_schema("DisplayNameControl", payload)
        ref = payload["ref"]
        context = _context(owner, vault, payload["rootKeyId"], ref)
        if (
            any(payload[key] != value for key, value in context.items())
            or ref["kind"] != "holdings"
            or ref["resourceId"] != source
        ):
            raise ContractError("not_found")
        if payload["stableOperationId"] != operation:
            raise ContractError("idempotency_conflict")
        name, op = _path(context), _path(context, operation)

        def replay(item):
            checked = _item(item, context)
            check_display_name_replay(checked["state"], signed, context=payload)
            return _response(item=checked)

        try:
            fence_cell = (HOLDINGS_FENCES, holdings_fence_key(owner, vault, source))
            previous, saved, fence = self.cutover._read((name, op, fence_cell))
            if fence is None or HoldingsFence.model_validate(fence).state == "deleted":
                raise ContractError("not_found")
            if saved is not None:
                return replay(saved)
            now = int(self.clock())
            sample, registry, _ = current_registry(self.cutover, uid, vault, now)
            if sample["rootKeyId"] != context["rootKeyId"]:
                raise ContractError("not_found")
            checked = _item(previous, context)
            state = plan_display_name_update(
                signed,
                registry=registry,
                owner_subject=owner,
                vault_id=vault,
                resource_ref=ref,
                current_state=None if checked is None else checked["state"],
                now=now,
            )
            item = {"state": state, "command": signed}

            def commit(read, write):
                existing, result = read((name, op))
                if result is not None:
                    fence = read((fence_cell,))[0]
                    if fence is None or HoldingsFence.model_validate(fence).state == "deleted":
                        raise ContractError("not_found")
                    return replay(result)
                head, _, entries = self._head(read, owner, vault)
                if existing != previous or not _matches_current(head, sample):
                    raise ContractError("version_conflict")
                if not any(
                    row["state"] == "active" and row["binding"]["ref"] == ref for row in entries
                ):
                    raise ContractError("not_found")
                write({name: item, op: item})
                return _response(item=item)

            return self.cutover._transaction(
                commit, writes=True, replace=(name,) if previous is not None else ()
            )
        except ResourceUnavailable as error:
            if isinstance(error.__cause__, ContractError):
                raise error.__cause__ from None
            raise ContractError("authorization_unavailable") from None
        except ValidationError:
            raise ContractError("authorization_unavailable") from None
