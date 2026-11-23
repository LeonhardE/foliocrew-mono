"""Market snapshots and signed-in refreshes without user-configuration handlers."""

import os
from typing import Annotated, Literal

from fastapi import Depends, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from folioview_shared.http import PrivateResponseHeaders, create_app

from .cost_controls import MarketCostRoute
from .instrument_search import router as instrument_search_router
from .manual_quote_access import require_manual_quote_user
from .market_data import MarketService, get_market_service
from .search_access import install_search_access
from .stock_metrics import router as stock_metrics_router
from .valuation_fx import router as valuation_fx_router
from .valuation_http import public_request
from .valuation_quotes import router as valuation_quotes_router
from .yahoo_provider import HISTORY_RANGES, SYMBOL_PATTERN, canonical_symbol

app = create_app(
    "FolioView Market API",
    description="Anonymous cached US market snapshots, instruments, and chart data.",
    methods=("GET", "POST"),
)
app.router.route_class = MarketCostRoute
app.add_middleware(PrivateResponseHeaders, prefixes=("/api/valuation/", "/api/stocks/refresh"))
install_search_access(app)
app.include_router(stock_metrics_router)
app.include_router(valuation_fx_router)
app.include_router(valuation_quotes_router)
app.include_router(instrument_search_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "market",
        "data_source": os.getenv("MARKET_DATA_SOURCE", "yfinance"),
    }


@app.get("/api/stocks", response_model=None)
def list_stocks(
    service: Annotated[MarketService, Depends(get_market_service)],
    response: Response,
    cached: Annotated[bool, Query()] = False,
) -> dict | Response:
    result = service.overview(cached_only=cached)
    if cached:
        response.headers["Cache-Control"] = "no-store"
    return (
        result
        if result is not None
        else Response(status_code=204, headers={"Cache-Control": "no-store"})
    )


@app.get("/api/stocks/search")
def search_stocks(
    service: Annotated[MarketService, Depends(get_market_service)],
    q: Annotated[str, Query(min_length=1, max_length=50)],
) -> dict:
    return service.search(q)


@app.get("/api/stocks/{symbol}/candles", response_model=None)
def stock_candles(
    symbol: str,
    service: Annotated[MarketService, Depends(get_market_service)],
    response: Response,
    range: Annotated[Literal["1d", "1w", "1m", "3m", "1y"], Query()] = "1m",
    cached: Annotated[bool, Query()] = False,
) -> dict | Response:
    result = service.candles(symbol, range, cached_only=cached)
    if cached:
        response.headers["Cache-Control"] = "no-store"
    return (
        result
        if result is not None
        else Response(status_code=204, headers={"Cache-Control": "no-store"})
    )


def market_refresh_request(value):
    if value == {"kind": "overview"}:
        return value
    if (
        type(value) is dict
        and set(value) == {"kind", "symbol", "range"}
        and value["kind"] == "candles"
        and type(value["symbol"]) is str
        and SYMBOL_PATTERN.fullmatch(canonical_symbol(value["symbol"]))
        and type(value["range"]) is str
        and value["range"] in HISTORY_RANGES
    ):
        return value
    raise ValueError("Invalid market refresh")


async def read_market_refresh(request: Request):
    return await public_request(request, market_refresh_request, 512, "market refresh")


@app.post("/api/stocks/refresh", dependencies=[Depends(require_manual_quote_user)])
async def refresh_stocks(
    value: Annotated[dict, Depends(read_market_refresh)],
    service: Annotated[MarketService, Depends(get_market_service)],
) -> dict:
    if value["kind"] == "overview":
        return await run_in_threadpool(service.overview, manual=True)
    return await run_in_threadpool(service.candles, value["symbol"], value["range"], manual=True)
