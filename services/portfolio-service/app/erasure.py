"""Physically remove one terminal holdings source after its remote fence is durable."""

import os

from folioview_shared.encrypted.errors import ContractError

from .lifecycle import mutation_path, mutation_record, state_path
from .store import SOURCE_HISTORY_COLLECTIONS, StoreUnavailable, document_path

# A page of even maximum-size snapshots fits within Firestore's 10 MiB commit.
_PAGE = 8
# A single opaque counter invalidates authority fetches started before a purge.
# It carries no source IDs, account IDs, key material or deletion history.
_GENERATION = document_path("portfolio_erasure_generation", "authority-fetch")


def authority_generation(unit):
    value = unit.get(_GENERATION)
    if value is None:
        return 0
    if value.keys() != {"generation"} or type(value["generation"]) is not int:
        raise StoreUnavailable
    return value["generation"]


def purge_source(store, owner, source, *, operation=None, now):
    """A crash leaves the existing acknowledged fence available for a retry.

    No explicit command can stage a deletion here. Every transaction rechecks
    the stored terminal ACK and its scope before deleting anything.
    """
    state_ref = state_path(owner, source)
    auth_ref = document_path("portfolio_authorities", owner, source)
    head_ref = document_path("portfolio_heads", owner, source)

    def terminal(unit):
        state = unit.get(state_ref)
        if state is None:
            return None
        if state.get("state") != "deleted" or state.get("pendingMutationId") is not None:
            raise ContractError("version_conflict")
        if state.get("ownerSubject") != owner or state.get("sourceId") != source:
            raise StoreUnavailable
        last = state["lastMutationId"]
        if operation is not None and last != operation:
            raise ContractError("version_conflict")
        retained = mutation_path(owner, source, last)
        ack = mutation_record(
            unit.get(retained),
            owner=owner,
            source=source,
            operation=last,
            resource_ref=state["resourceRef"],
        )
        if (
            ack["action"] != "delete"
            or ack["state"] != "acknowledged"
            or ack["sourceEpoch"] != state["sourceEpoch"]
        ):
            raise StoreUnavailable
        return retained, ack

    def retirement_request(unit):
        terminal_row = terminal(unit)
        if terminal_row is None:
            return None
        _, ack = terminal_row
        authority = unit.get(auth_ref)
        if (
            not authority
            or authority.get("ownerSubject") != owner
            or authority.get("sourceId") != source
        ):
            raise StoreUnavailable
        if (
            ack.get("legacyHubPending")
            or "registryStart" in authority
            or os.getenv("PORTFOLIO_USER_AUTHORITY_OWNER") == owner
        ):
            return ack
        return None

    confirmed = store.transact(retirement_request)
    if confirmed is not None:
        from .fence_sync import confirm_legacy_hub_retirement

        confirm_legacy_hub_retirement(confirmed)

    def page(unit):
        row = terminal(unit)
        if row is None:
            return True
        retained, ack = row
        if confirmed is not None and confirmed != ack:
            raise StoreUnavailable
        from .upload_cancellations import prune_source_cancellations

        prune_source_cancellations(unit, owner, source, ack, now)
        for collection in SOURCE_HISTORY_COLLECTIONS:
            paths = unit.erasure_page(collection, owner=owner, source=source, limit=_PAGE + 1)
            deletions = []
            for path, saved_owner, saved_source in paths:
                if (
                    saved_owner != owner
                    or saved_source != source
                    or not path.startswith(collection + "/")
                ):
                    raise StoreUnavailable
                if path != retained:
                    deletions.append(path)
            if deletions:
                for path in deletions[:_PAGE]:
                    unit.delete(path)
                return False
        for path in (head_ref, auth_ref):
            row = unit.get(path)
            if row is not None and (
                row.get("ownerSubject") != owner or row.get("sourceId") != source
            ):
                raise StoreUnavailable
        generation = authority_generation(unit)
        for path in (head_ref, auth_ref, retained, state_ref):
            unit.delete(path)
        unit.put(_GENERATION, {"generation": generation + 1})
        return True

    while not store.transact(page):
        pass


def legacy_sources(store):
    """Enumerate terminal rows without retrieving portfolio contents."""
    after = None
    while True:
        rows = store.transact(
            lambda unit, cursor=after: unit.erasure_page(
                "portfolio_source_states", limit=64, after=cursor
            )
        )
        for path, owner, source in rows:
            if path != state_path(owner, source):
                raise StoreUnavailable
            yield owner, source
        if len(rows) < 64:
            return
        after = rows[-1][0]
