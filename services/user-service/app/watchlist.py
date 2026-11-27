"""Private bounded watchlists, isolated by verified identity and durable across restarts."""

import json
import os
import sqlite3
import time
from contextlib import closing, contextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path as FilePath
from typing import Annotated, Literal, NamedTuple

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from google.cloud import firestore
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from folioview_shared.auth import CurrentUser, require_google_user
from folioview_shared.encrypted.jsonutil import strict_json_loads
from folioview_shared.firestore import BoundedTransaction
from folioview_shared.http import PrivateRoute
from folioview_shared.identity import owner_key
from folioview_shared.instruments import (
    DEFAULT_BY_SYMBOL,
    SYMBOL_PATTERN,
    canonical_symbol,
    iso_time,
)
from folioview_shared.valuation import (
    FX_PREFERENCES_PROFILE,
    VALUATION_CONTRACT,
    ValuationError,
    fx_preferences_snapshot,
    next_fx_preferences_snapshot,
)

from .firestore_reads import read_documents
from .list_writes import require_list_writes
from .market_client import MarketResolver, get_market_resolver
from .resource_versions import MAX_REVISION, new_version, validate_version, version_key

LIMIT = 50
UNAVAILABLE = "Your watchlist is temporarily unavailable. Please try again later."


class WatchlistUnavailable(Exception):
    """Storage or stored data could not be used safely."""


class WatchlistFull(Exception):
    """The bounded user document is full."""


class WatchlistItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    symbol: Annotated[str, Field(min_length=1, max_length=14)]
    name: Annotated[str, Field(min_length=1, max_length=180)]
    instrumentType: Literal["stock", "index"]
    currency: Literal["USD"]
    addedAt: Annotated[str, Field(min_length=20, max_length=40)]


class WatchlistResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[WatchlistItem]
    limit: Literal[50] = LIMIT


class VersionedWatchlistResponse(WatchlistResponse):
    revision: Annotated[int, Field(ge=0, le=MAX_REVISION)] | None


class WatchlistSnapshot(NamedTuple):
    items: list[dict]
    revision: int | None


def checked_items(value: object) -> list[dict]:
    """Reject malformed stored documents rather than overwriting private data."""
    if value is None:
        return []
    if not isinstance(value, dict) or value.get("version") != 1:
        raise WatchlistUnavailable
    rows = value.get("items")
    if not isinstance(rows, list) or len(rows) > LIMIT:
        raise WatchlistUnavailable
    result = []
    symbols = set()
    try:
        for row in rows:
            item = WatchlistItem.model_validate(row).model_dump()
            timestamp = datetime.fromisoformat(item["addedAt"].replace("Z", "+00:00"))
            if (
                not SYMBOL_PATTERN.fullmatch(item["symbol"])
                or item["symbol"] in symbols
                or timestamp.tzinfo is None
                or (
                    item["instrumentType"] == "index"
                    and (
                        item["symbol"] not in DEFAULT_BY_SYMBOL
                        or DEFAULT_BY_SYMBOL[item["symbol"]].instrument_type != "index"
                    )
                )
            ):
                raise WatchlistUnavailable
            symbols.add(item["symbol"])
            result.append(item)
        return sorted(
            result,
            key=lambda item: (
                datetime.fromisoformat(item["addedAt"].replace("Z", "+00:00")),
                item["symbol"],
            ),
        )
    except (ValueError, TypeError, KeyError) as error:
        raise WatchlistUnavailable from error


def checked_pair(content: object, metadata: object) -> tuple[list[dict], dict | None]:
    if content is None and metadata is not None:
        raise WatchlistUnavailable
    items = checked_items(content)
    return items, validate_version("watchlist", items, metadata)


def versioned_snapshot(items: list[dict], metadata: dict | None) -> WatchlistSnapshot:
    return WatchlistSnapshot(items, metadata["revision"] if metadata is not None else None)


def update_items(items: list[dict], symbol: str, item: dict | None) -> tuple[list[dict], bool]:
    existing = any(row["symbol"] == symbol for row in items)
    if item is not None:
        if existing:
            return items, False
        if len(items) >= LIMIT:
            raise WatchlistFull
        return checked_items({"version": 1, "items": [*items, item]}), True
    return [row for row in items if row["symbol"] != symbol], existing


class FxPreferencesConflict(Exception):
    """A newer Owner FX preference save already completed."""


def fx_owner(uid: str) -> str:
    return "fx.v1:" + owner_key(uid)


def empty_fx() -> dict:
    return {
        "contractVersion": VALUATION_CONTRACT,
        "profile": FX_PREFERENCES_PROFILE,
        "preferences": None,
        "version": 0,
    }


def checked_fx_record(value) -> dict:
    try:
        result = fx_preferences_snapshot(value)
        if result["preferences"] is None:
            raise ValuationError
        return result
    except ValuationError:
        raise WatchlistUnavailable from None


def next_fx(current, update):
    try:
        return next_fx_preferences_snapshot(current, update)
    except ValuationError as error:
        if error.code == "version_conflict":
            raise FxPreferencesConflict from None
        raise WatchlistUnavailable from None


class WatchlistStore:
    def get_fx(self, uid: str) -> dict:
        raise NotImplementedError

    def save_fx(self, uid: str, update: dict) -> dict:
        raise NotImplementedError

    def get(self, uid: str) -> list[dict]:
        raise NotImplementedError

    def get_snapshot(self, uid: str) -> WatchlistSnapshot:
        raise NotImplementedError

    def change(self, uid: str, symbol: str, item: dict | None) -> list[dict]:
        return self.change_snapshot(uid, symbol, item).items

    def change_snapshot(self, uid: str, symbol: str, item: dict | None) -> WatchlistSnapshot:
        raise NotImplementedError


class SQLiteWatchlistStore(WatchlistStore):
    """Persistent local development storage; never used in Cloud Run."""

    def __init__(self, path: str):
        self.path = path
        try:
            FilePath(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with self.connection() as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS user_watchlists "
                    "(owner TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS user_resource_versions "
                    "(owner TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
            FilePath(path).chmod(0o600)
        except OSError as error:
            raise WatchlistUnavailable from error

    @contextmanager
    def connection(self):
        try:
            with closing(sqlite3.connect(self.path, timeout=3)) as db, db:
                yield db
        except (sqlite3.Error, OSError, ValueError, TypeError) as error:
            raise WatchlistUnavailable from error

    @staticmethod
    def read(db, owner):
        row = db.execute("SELECT value FROM user_watchlists WHERE owner=?", (owner,)).fetchone()
        return checked_items(json.loads(row[0]) if row else None)

    def get(self, uid: str) -> list[dict]:
        with self.connection() as db:
            return self.read(db, owner_key(uid))

    @staticmethod
    def read_pair(db, uid: str) -> tuple[list[dict], dict | None]:
        owner = owner_key(uid)
        content = db.execute("SELECT value FROM user_watchlists WHERE owner=?", (owner,)).fetchone()
        metadata = db.execute(
            "SELECT value FROM user_resource_versions WHERE owner=?",
            (version_key(uid, "watchlist"),),
        ).fetchone()
        content_value = strict_json_loads(content[0]) if content else None
        metadata_value = strict_json_loads(metadata[0]) if metadata else None
        if (content and content_value is None) or (metadata and metadata_value is None):
            raise WatchlistUnavailable
        return checked_pair(content_value, metadata_value)

    def get_snapshot(self, uid: str) -> WatchlistSnapshot:
        with self.connection() as db:
            db.execute("BEGIN")
            return versioned_snapshot(*self.read_pair(db, uid))

    def change_snapshot(self, uid: str, symbol: str, item: dict | None) -> WatchlistSnapshot:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current, metadata = self.read_pair(db, uid)
            items, changed = update_items(current, symbol, item)
            if changed:
                require_list_writes(WatchlistUnavailable)
                metadata = new_version("watchlist", items, previous=metadata)
                db.execute(
                    "INSERT INTO user_watchlists(owner, value) VALUES (?, ?) "
                    "ON CONFLICT(owner) DO UPDATE SET value=excluded.value",
                    (owner_key(uid), json.dumps({"version": 1, "items": items}, allow_nan=False)),
                )
                db.execute(
                    "INSERT INTO user_resource_versions(owner, value) VALUES (?, ?) "
                    "ON CONFLICT(owner) DO UPDATE SET value=excluded.value",
                    (
                        version_key(uid, "watchlist"),
                        json.dumps(metadata, allow_nan=False),
                    ),
                )
            return versioned_snapshot(items, metadata)

    @staticmethod
    def read_fx(db, owner: str) -> dict:
        row = db.execute("SELECT value FROM user_watchlists WHERE owner=?", (owner,)).fetchone()
        return checked_fx_record(strict_json_loads(row[0])) if row else empty_fx()

    def get_fx(self, uid: str) -> dict:
        with self.connection() as db:
            return self.read_fx(db, fx_owner(uid))

    def save_fx(self, uid: str, update: dict) -> dict:
        owner = fx_owner(uid)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            result = next_fx(self.read_fx(db, owner), update)
            require_list_writes(WatchlistUnavailable)
            db.execute(
                "INSERT INTO user_watchlists(owner,value) VALUES (?,?) "
                "ON CONFLICT(owner) DO UPDATE SET value=excluded.value",
                (owner, json.dumps(result, allow_nan=False)),
            )
            return result


class FirestoreWatchlistStore(WatchlistStore):
    """One user document, one bounded read, and atomic capped modifications."""

    def __init__(self, project: str, database: str):
        try:
            self.client = firestore.Client(project=project, database=database)
            self.collection = self.client.collection("user_watchlists")
        except Exception as error:
            raise WatchlistUnavailable from error

    def document(self, uid: str):
        return self.collection.document(owner_key(uid))

    def get(self, uid: str) -> list[dict]:
        try:
            return checked_items(self.document(uid).get(timeout=4, retry=None).to_dict())
        except Exception as error:
            raise WatchlistUnavailable from error

    def references(self, uid: str):
        return (
            self.document(uid),
            self.client.collection("user_resource_versions").document(
                version_key(uid, "watchlist")
            ),
        )

    def get_snapshot(self, uid: str) -> WatchlistSnapshot:
        @firestore.transactional
        def read_transaction(transaction):
            pair = read_documents(self.client, transaction, self.references(uid))
            return versioned_snapshot(*checked_pair(*pair))

        try:
            return read_transaction(BoundedTransaction(self.client, max_attempts=2))
        except Exception as error:
            raise WatchlistUnavailable from error

    def change_snapshot(self, uid: str, symbol: str, item: dict | None) -> WatchlistSnapshot:
        reference, metadata_reference = self.references(uid)

        @firestore.transactional
        def change_transaction(transaction):
            current_items, metadata = checked_pair(
                *read_documents(self.client, transaction, [reference, metadata_reference])
            )
            items, changed = update_items(current_items, symbol, item)
            if changed:
                require_list_writes(WatchlistUnavailable)
                metadata = new_version("watchlist", items, previous=metadata)
                transaction.set(reference, {"version": 1, "items": items})
                transaction.set(metadata_reference, metadata)
            return versioned_snapshot(items, metadata)

        try:
            return change_transaction(BoundedTransaction(self.client, max_attempts=2))
        except WatchlistFull:
            raise
        except Exception as error:
            raise WatchlistUnavailable from error

    def get_fx(self, uid: str) -> dict:
        try:
            value = self.collection.document(fx_owner(uid)).get(timeout=4, retry=None).to_dict()
            return checked_fx_record(value) if value is not None else empty_fx()
        except Exception as error:
            raise WatchlistUnavailable from error

    def save_fx(self, uid: str, update: dict) -> dict:
        reference = self.collection.document(fx_owner(uid))

        @firestore.transactional
        def save_transaction(transaction):
            value = reference.get(transaction=transaction, timeout=4, retry=None).to_dict()
            current = checked_fx_record(value) if value is not None else empty_fx()
            result = next_fx(current, update)
            require_list_writes(WatchlistUnavailable)
            transaction.set(reference, result)
            return result

        try:
            return save_transaction(BoundedTransaction(self.client, max_attempts=2))
        except FxPreferencesConflict:
            raise
        except Exception as error:
            raise WatchlistUnavailable from error


def create_watchlist_store() -> WatchlistStore:
    on_cloud_run = "K_SERVICE" in os.environ
    backend = os.getenv("USER_STORE_BACKEND") or os.getenv(
        "MARKET_CACHE_BACKEND", "firestore" if on_cloud_run else "sqlite"
    )
    if on_cloud_run and (
        backend != "firestore"
        or os.getenv("FIRESTORE_EMULATOR_HOST")
        or os.getenv("FIREBASE_AUTH_EMULATOR_HOST")
    ):
        raise WatchlistUnavailable
    if backend == "firestore":
        project = os.getenv("FIREBASE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise WatchlistUnavailable
        database = os.getenv("FIRESTORE_DATABASE") or os.getenv(
            "MARKET_FIRESTORE_DATABASE", "(default)"
        )
        return FirestoreWatchlistStore(project, database)
    if backend == "sqlite":
        return SQLiteWatchlistStore(
            os.getenv("WATCHLIST_DB_PATH", "/tmp/financial-analysis/watchlists.sqlite3")
        )
    raise WatchlistUnavailable


@lru_cache(maxsize=4)
def configured_store(configuration: tuple[str, ...]) -> WatchlistStore:
    # Cache database clients, never user responses or identity information.
    return create_watchlist_store()


def get_watchlist_store() -> WatchlistStore:
    configuration = tuple(
        os.getenv(key, "")
        for key in (
            "USER_STORE_BACKEND",
            "FIRESTORE_DATABASE",
            "MARKET_CACHE_BACKEND",
            "MARKET_FIRESTORE_DATABASE",
            "FIREBASE_PROJECT_ID",
            "GOOGLE_CLOUD_PROJECT",
            "K_SERVICE",
            "WATCHLIST_DB_PATH",
            "FIRESTORE_EMULATOR_HOST",
            "FIREBASE_AUTH_EMULATOR_HOST",
        )
    ) + (str("K_SERVICE" in os.environ),)
    try:
        return configured_store(configuration)
    except WatchlistUnavailable as error:
        raise HTTPException(503, UNAVAILABLE) from error


def validated_symbol(raw: str) -> str:
    symbol = canonical_symbol(raw)
    if not SYMBOL_PATTERN.fullmatch(symbol):
        raise HTTPException(400, "Invalid stock symbol")
    return symbol


def response(items: list[dict]) -> dict:
    return {"items": items, "limit": LIMIT}


class PrivateWatchlistRoute(PrivateRoute):
    unavailable_message = UNAVAILABLE


router = APIRouter(
    prefix="/api/v1/watchlist", tags=["watchlist"], route_class=PrivateWatchlistRoute
)
User = Annotated[CurrentUser, Depends(require_google_user)]
Store = Annotated[WatchlistStore, Depends(get_watchlist_store)]
Symbol = Annotated[str, Path(min_length=1, max_length=32)]
IncludeRevision = Annotated[bool, Query(alias="includeRevision")]


def snapshot_response(snapshot: WatchlistSnapshot, include_revision: bool) -> dict:
    result = response(snapshot.items)
    if include_revision:
        result["revision"] = snapshot.revision
    return result


@router.get("", response_model=VersionedWatchlistResponse | WatchlistResponse)
def list_watchlist(user: User, store: Store, include_revision: IncludeRevision = False) -> dict:
    try:
        if include_revision:
            return snapshot_response(store.get_snapshot(user.uid), include_revision)
        return response(store.get(user.uid))
    except WatchlistUnavailable as error:
        raise HTTPException(503, UNAVAILABLE) from error


@router.put("/{symbol}", response_model=VersionedWatchlistResponse | WatchlistResponse)
async def add_watchlist_item(
    symbol: Symbol,
    user: User,
    store: Store,
    market: Annotated[MarketResolver, Depends(get_market_resolver)],
    include_revision: IncludeRevision = False,
) -> dict:
    symbol = validated_symbol(symbol)
    try:
        if include_revision:
            current = await run_in_threadpool(store.get_snapshot, user.uid)
        else:
            current = WatchlistSnapshot(await run_in_threadpool(store.get, user.uid), None)
        # No upstream lookup, timestamp change, or database write on duplicate add.
        if any(item["symbol"] == symbol for item in current.items):
            return snapshot_response(current, include_revision)
        if len(current.items) >= LIMIT:
            raise WatchlistFull
        instrument = await market.resolve(symbol)
        item = {**instrument.public(), "addedAt": iso_time(time.time())}
        if item["symbol"] != symbol:
            raise WatchlistUnavailable
        saved = await run_in_threadpool(store.change_snapshot, user.uid, symbol, item)
        return snapshot_response(saved, include_revision)
    except WatchlistFull as error:
        raise HTTPException(409, f"Your watchlist can contain up to {LIMIT} instruments") from error
    except WatchlistUnavailable as error:
        raise HTTPException(503, UNAVAILABLE) from error
    except HTTPException as error:
        if error.status_code in (429, 503):
            raise HTTPException(503, "Stock validation is temporarily unavailable") from error
        raise


@router.delete("/{symbol}", response_model=VersionedWatchlistResponse | WatchlistResponse)
def remove_watchlist_item(
    symbol: Symbol, user: User, store: Store, include_revision: IncludeRevision = False
) -> dict:
    symbol = validated_symbol(symbol)
    try:
        # Removal and listing work even when Yahoo or the market cache is down.
        return snapshot_response(store.change_snapshot(user.uid, symbol, None), include_revision)
    except WatchlistUnavailable as error:
        raise HTTPException(503, UNAVAILABLE) from error
