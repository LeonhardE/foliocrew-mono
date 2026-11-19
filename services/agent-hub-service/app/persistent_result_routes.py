"""Current Agent report producer and separate Google-owner history/control routes."""

import os
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.http import PrivateRoute

from .agent_transport import recovery_transport
from .api import Owner, _invoke, body, transport
from .persistent_execution_routes import get_execution
from .persistent_results import PersistentOwnerResultService, PersistentResultService
from .store import get_store

agent_router = APIRouter(
    prefix="/agent/v3/persistent/owners/{owner}/vaults/{vault}/connections/{connection}",
    route_class=PrivateRoute,
)
owner_router = APIRouter(prefix="/api/v2/persistent-results", route_class=PrivateRoute)


def _protocol(request, *, write=False, allowed=frozenset()):
    if request.headers.getlist("x-folioview-delegation") or request.headers.getlist(
        "x-serverless-authorization"
    ):
        raise ContractError("insufficient_scope")
    if write:
        transport(request, operation=True, author=True)
    else:
        if request.headers.getlist("x-folioview-contract") != [CONTRACT_VERSION]:
            raise ContractError("unsupported_contract")
        if set(request.query_params) - allowed or any(
            len(request.query_params.getlist(key)) != 1 for key in request.query_params
        ):
            raise ContractError("unsupported_query")


def _number(value, *, maximum=50, query=False):
    if (
        type(value) is not str
        or not value.isascii()
        or not value.isdecimal()
        or len(value) > len(str(maximum))
        or str(int(value)) != value
        or not 1 <= int(value) <= maximum
    ):
        raise ContractError("unsupported_query" if query else "malformed_request")
    return int(value)


def get_result_writer():
    def configured():
        if os.getenv("HUB_PERSISTENT_RESULTS_ENABLED") != "1":
            raise ContractError("authorization_unavailable")
        current = get_execution()
        return PersistentResultService(
            current.store,
            current.catalogue,
            audience=current.audience,
            managed_only=True,
            client_ids=current.client_ids,
            clock=current.clock,
        )

    return _invoke(configured)


def get_result_history():
    return PersistentOwnerResultService(get_store(), clock=time.time)


Writer = Annotated[PersistentResultService, Depends(get_result_writer)]
History = Annotated[PersistentOwnerResultService, Depends(get_result_history)]


@agent_router.post("/runs/submit", status_code=201)
async def submit(owner: str, vault: str, connection: str, request: Request, service: Writer):
    _invoke(lambda: recovery_transport(request))
    value = await body(request, {"contractVersion", "proof", "request"}, max_bytes=557056)
    return await run_in_threadpool(
        _invoke,
        lambda: service.submit(
            owner, vault, connection, value["proof"], request.url.path, value["request"]
        ),
    )


@agent_router.post("/runs/result-receipt")
async def receipt(owner: str, vault: str, connection: str, request: Request, service: Writer):
    _invoke(lambda: recovery_transport(request))
    value = await body(request, {"contractVersion", "proof", "request"}, max_bytes=24576)
    return await run_in_threadpool(
        _invoke,
        lambda: service.result_receipt(
            owner, vault, connection, value["proof"], request.url.path, value["request"]
        ),
    )


@owner_router.get("/{vault_id}")
def results(vault_id: str, request: Request, user: Owner, service: History):
    _invoke(lambda: _protocol(request, allowed={"limit", "cursor"}))
    limit = _invoke(lambda: _number(request.query_params.get("limit", "20"), query=True))
    return _invoke(
        lambda: service.owner_list(
            user.uid, vault_id, limit=limit, cursor=request.query_params.get("cursor")
        )
    )


@owner_router.get("/{vault_id}/{result_id}")
def result(vault_id: str, result_id: str, request: Request, user: Owner, service: History):
    _invoke(lambda: _protocol(request))
    return _invoke(lambda: service.owner_get(user.uid, vault_id, result_id))


@owner_router.patch("/{vault_id}/{result_id}/state")
async def state(vault_id: str, result_id: str, request: Request, user: Owner, service: History):
    _invoke(lambda: _protocol(request, write=True))
    value = await body(request, {"contractVersion", "command"}, max_bytes=24576)
    return await run_in_threadpool(
        _invoke,
        lambda: service.owner_state(
            user.uid,
            vault_id,
            result_id,
            value["command"],
            request.headers["idempotency-key"],
            request.headers["x-folioview-author-key"],
        ),
    )
