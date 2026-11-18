"""Private single-task browse read; the original control and execution paths own authorization."""

from folioview_shared.encrypted.budgets import check_read_response
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.schema import validate_schema
from folioview_shared.identity import owner_key

from .native_transport import PROFILE as ACCOUNT_PROFILE
from .native_transport import NativeConnectionOwnerService
from .persistent_publications import stored_task_state
from .store import StoreUnavailable, document_path
from .task_center import task_metadata, task_path
from .task_lifecycle import lifecycle_path, require_visible
from .tasks import _paths, _response, _TaskReadView
from .vaults import _current

PROFILE = "folioview.owner-task-detail.v1"


def _optional(read):
    try:
        return {"status": "ready", "data": read()}
    except (ContractError, StoreUnavailable):
        return {"status": "unavailable"}


def _attribution(unit, native, uid, owner, vault, connection):
    connection_path = document_path("hub_oauth_connections", owner, connection)
    paths = [document_path("hub_oauth_owners", owner), connection_path]
    view = _TaskReadView(unit, unit.get_many(paths))
    index = native._owner(view, uid)
    if connection not in index["connectionIds"]:
        raise StoreUnavailable
    row = view.get(connection_path)
    if (
        not isinstance(row, dict)
        or row.get("ownerSubject") != owner
        or row.get("vaultId") != vault
        or row.get("connectionId") != connection
        or row.get("transportKind") != "persistent_runtime"
        or row.get("provider") not in ("muse", "chatgpt")
    ):
        raise StoreUnavailable
    try:
        connection_view = native._view(row)
        if type(connection_view["linkedAt"]) is not int or connection_view["linkedAt"] < 0:
            raise StoreUnavailable
    except (TypeError, KeyError):
        raise StoreUnavailable from None
    return {
        "contractVersion": CONTRACT_VERSION,
        "profile": ACCOUNT_PROFILE,
        "connections": [connection_view],
    }


def _current_packet(unit, owner, vault, task, meta):
    packet = _response(unit, owner, vault, task, meta["taskVersion"])
    if packet["metadata"] != meta:
        raise StoreUnavailable
    return packet


def _fit(result):
    # Prefer the original executor evidence when the two independent carriers do not fit together.
    for field in ("packet", "legacy"):
        try:
            check_read_response(result)
            return result
        except ContractError as error:
            if error.code != "payload_too_large":
                raise
        if result[field] and result[field]["status"] == "ready":
            result[field] = {"status": "unavailable"}
            if field == "legacy":
                result["attribution"] = None
    check_read_response(result)
    return result


def read_task_detail(service, uid, vault, task, options):
    if (
        type(options) is not dict
        or set(options) != {"contractVersion", "includePacket", "includeAttribution"}
        or options["contractVersion"] != CONTRACT_VERSION
        or type(options["includePacket"]) is not bool
        or type(options["includeAttribution"]) is not bool
    ):
        raise ContractError("malformed_request")
    for ident in (vault, task):
        validate_schema("Identifier", ident)

    def read(unit):
        owner = owner_key(uid)
        v, _ = _current(unit, owner, service.now(), vault)
        paths = [
            document_path("hub_task_indexes", owner, vault),
            _paths(owner, vault, task),
            lifecycle_path(owner, vault),
            task_path(owner, vault, task),
        ]
        view = _TaskReadView(unit, unit.get_many(paths))
        require_visible(view, owner, vault, task)
        meta = task_metadata(view, owner, vault, task)
        state = service._state(view, owner, vault, task, meta)
        result = {
            "contractVersion": CONTRACT_VERSION,
            "profile": PROFILE,
            "state": state,
            "legacy": None,
            "attribution": None,
            "packet": None,
        }
        if state["rules"] is None and meta["status"] == "active" and meta["resourceBindings"]:
            result["legacy"] = _optional(lambda: stored_task_state(unit, owner, vault, task))
            authority = result["legacy"].get("data", {}).get("authority")
            if options["includeAttribution"] and authority:
                c = authority["context"]
                if (
                    c["rootKeyId"] == v["rootKeyId"]
                    and c["taskVersion"] == meta["taskVersion"]
                    and c["executionEpoch"] == meta["executionEpoch"]
                    and c["ownerTaskFingerprint"] == meta["envelopeFingerprint"]
                ):
                    result["attribution"] = _optional(
                        lambda: _attribution(
                            unit,
                            NativeConnectionOwnerService(service.store, clock=service.clock),
                            uid,
                            owner,
                            vault,
                            c["connectionId"],
                        )
                    )
        if options["includePacket"]:
            result["packet"] = _optional(lambda: _current_packet(unit, owner, v, task, meta))
        return _fit(result)

    return service.store.transact(read)
