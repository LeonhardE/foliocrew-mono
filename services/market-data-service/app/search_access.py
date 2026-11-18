"""Keep search terms out of Uvicorn access logs while preserving request diagnostics."""

import json
import logging
import sys
from contextvars import ContextVar
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SEARCH_PATHS = {"/api/stocks/search", "/api/stocks/search/"}
_request: ContextVar[tuple[str, float] | None] = ContextVar("market_search_request", default=None)
_search_log = logging.getLogger("market.search.access")


def _filter_access(record: logging.LogRecord) -> bool:
    # Uvicorn's h11 and httptools protocols emit (client, method, target, version, status).
    args = record.args
    context = _request.get()
    if not isinstance(args, tuple) or len(args) != 5 or not isinstance(args[2], str):
        return context is None
    if context is None and args[2].partition("?")[0] not in SEARCH_PATHS:
        return True
    if not isinstance(args[4], int) or not 100 <= args[4] <= 599:
        return False
    event = {"event": "http_request", "route": "stock_search", "status": args[4]}
    if context is not None:
        request_id, started = context
        event.update(request_id=request_id, duration_ms=round((perf_counter() - started) * 1000, 3))
    _search_log.info(json.dumps(event, separators=(",", ":")))
    return False


class SearchAccess:
    """Time search requests through response headers, including validation and admission errors."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or scope["path"] not in SEARCH_PATHS:
            return await self.app(scope, receive, send)
        request_id = uuid4().hex
        token = _request.set((request_id, perf_counter()))

        async def identify(message: Message):
            if message["type"] == "http.response.start":
                headers = [*message.get("headers", ()), (b"x-request-id", request_id.encode())]
                message = {**message, "headers": headers}
            await send(message)

        try:
            return await self.app(scope, receive, identify)
        finally:
            _request.reset(token)


def install_search_access(app: FastAPI):
    if not _search_log.handlers:
        _search_log.addHandler(logging.StreamHandler(sys.stdout))
    _search_log.propagate = False
    _search_log.setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").addFilter(_filter_access)
    app.add_middleware(SearchAccess)
