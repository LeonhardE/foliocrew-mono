"""Owner metadata composition with one bounded, freshly verified final snapshot."""

import copy
import logging

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from folioview_shared.encrypted.budgets import check_read_response
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json
from folioview_shared.http import PrivateRoute
from folioview_shared.identity import owner_key

from .api import Owner, Service, _invoke, _lifecycle_read
from .catalogue import (
    FINALIZE_SECONDS,
    TOTAL_SECONDS,
    CatalogueService,
    Sources,
    _context,
    _response,
    _scope,
    remaining,
)
from .fences import fence_path
from .persistent_routes import control_transport
from .private_display_names import _listing, display_name_capabilities, name_path
from .store import StoreUnavailable, document_path
from .vaults import MAX_SOURCES, _verify_row

PROFILE = "folioview.owner-resource-display.v1"
_TIMING_LOGGER = logging.getLogger("uvicorn.error.hub_resource_display")


def _response_body(scope, catalogue, capabilities, names):
    # Each original component must pass its own unchanged ceiling before the
    # combined envelope is considered. Only aggregate overflow selects fallback.
    for component in (catalogue, capabilities, names):
        check_read_response(component)
    value = {
        "contractVersion": CONTRACT_VERSION,
        "profile": PROFILE,
        "mode": "full",
        "scope": scope,
        "catalogue": catalogue,
        "displayNameCapabilities": capabilities,
        "displayNames": names,
    }
    try:
        check_read_response(value)
    except ContractError as error:
        if error.code != "payload_too_large":
            raise
        value = {
            "contractVersion": CONTRACT_VERSION,
            "profile": PROFILE,
            "mode": "separate",
            "reason": "aggregate_too_large",
        }
        check_read_response(value)
    return value


class ResourceDisplayService:
    def __init__(self, vaults, sources):
        self.vaults, self.sources = vaults, sources

    def read(self, uid):
        clock = self.sources.clock
        started = clock()
        deadline = started + TOTAL_SECONDS
        cache = {}
        owner = owner_key(uid)
        catalogue = CatalogueService(self.vaults, self.sources)
        timing = dict.fromkeys(("before", "discover", "after"), 0.0)
        stage_name, stage, mode, count = None, started, "error", 0
        try:
            stage_name = "before"
            before, scope, live = catalogue._snapshot(uid, registry_cache=cache)
            timing["before"] = clock() - stage
            stage_name = None
            if not live:
                # Composition is for an active verified Vault. The old catalogue
                # and capabilities GETs retain their independent no-Vault behavior.
                raise ContractError("not_found")
            refs = [source["ref"] for source in before["sources"]]
            count = len(refs)
            if count > MAX_SOURCES:
                raise StoreUnavailable
            vault_path = document_path("hub_vaults", owner)
            paths = [vault_path]
            for ref in refs:
                paths.extend(
                    (
                        fence_path(owner, ref),
                        name_path(owner, scope["vaultId"], scope["rootKeyId"], ref),
                    )
                )
            if len(paths) != 1 + 2 * count or len(set(paths)) != len(paths) or len(paths) > 21:
                raise StoreUnavailable
            expected_scope, expected_refs = canonical_json(scope), canonical_json(refs)
            expected_context = canonical_json(before)
            remaining(deadline - FINALIZE_SECONDS, clock)
            stage_name, stage = "discover", clock()
            result = self.sources.discover(
                uid, copy.deepcopy(before["sources"]), deadline=deadline - FINALIZE_SECONDS
            )
            timing["discover"] = clock() - stage
            stage_name = None
            remaining(deadline, clock)

            def after(unit):
                loaded = unit.get_many(paths)
                if any(path not in loaded for path in paths):
                    raise StoreUnavailable
                row = loaded[vault_path]
                if row is None:
                    raise ContractError("version_conflict")
                if type(row) is dict and "archive" in row and row["archive"] is None:
                    # No composition is returned after archive removal. Refuse
                    # before an optional lifecycle lookup can exceed this fixed
                    # read set; the original independent GETs remain unchanged.
                    raise ContractError("not_found")
                # Retry time belongs to this actual transaction attempt. The
                # exact-history cache only reuses existing static Root checks.
                registry = _verify_row(
                    row, owner, self.vaults.now(), unit=unit, registry_cache=cache
                )
                current_scope = _scope(owner, row, registry)
                current_refs = [source["resourceRef"] for source in row["sources"]]
                if (
                    canonical_json(current_scope) != expected_scope
                    or canonical_json(current_refs) != expected_refs
                    or canonical_json(_context(row, registry, owner, loaded)) != expected_context
                ):
                    raise ContractError("version_conflict")
                return current_scope, _listing(row, owner, row["vaultId"], loaded)

            stage_name, stage = "after", clock()
            final_scope, names = self.vaults.store.transact(after)
            timing["after"] = clock() - stage
            stage_name = None
            remaining(deadline, clock)
            value = _response_body(
                final_scope,
                _response(result, self.vaults.now()),
                display_name_capabilities(),
                names,
            )
            remaining(deadline, clock)
            mode = value["mode"]
            return value
        finally:
            if stage_name is not None:
                timing[stage_name] += clock() - stage
            _TIMING_LOGGER.info(
                "hub_resource_display sources=%d mode=%s before_ms=%.3f discover_ms=%.3f "
                "after_ms=%.3f total_ms=%.3f",
                count,
                mode,
                *(timing[name] * 1000 for name in ("before", "discover", "after")),
                (clock() - started) * 1000,
            )


router = APIRouter(prefix="/api/v3/resources", route_class=PrivateRoute)


@router.get("/display")
async def display(request: Request, user: Owner, vaults: Service, sources: Sources):
    def validate():
        control_transport(request)
        if request.headers.getlist("x-serverless-authorization"):
            raise ContractError("insufficient_scope")

    _invoke(validate)
    await _lifecycle_read(request)
    return await run_in_threadpool(
        _invoke, lambda: ResourceDisplayService(vaults, sources).read(user.uid)
    )
