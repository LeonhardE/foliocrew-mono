"""Account attribution at the internal storage boundary. These paths never cross HTTP."""

import re

from folioview_shared.encrypted.errors import ContractError
from folioview_shared.identity import owner_key

OWNER = re.compile(r"[0-9a-f]{64}\Z")
POOLS = {"hub_oauth_pending", "hub_native_oauth_pending"}
OPAQUE_KEYS = POOLS | {
    "hub_runtime_setup_intents",
    "hub_agent_credential_setups",
    *(
        "hub_" + prefix + suffix
        for prefix in ("oauth_", "native_oauth_")
        for suffix in ("codes", "access", "refresh", "families")
    ),
}
OWNERSHIP = "hub_account_ownership"
HOLDS = "hub_account_write_holds"


class OwnedPath(str):
    """Retain internal owner keys until the write is staged, including across a retry."""

    def __new__(cls, path, owner):
        obj = str.__new__(cls, path)
        obj.owner = owner
        return obj

    def __getnewargs__(self):
        return str(self), self.owner


def scoped_path(collection, path, parts):
    if (
        collection not in OPAQUE_KEYS | {HOLDS, OWNERSHIP}
        and parts
        and isinstance(parts[0], str)
        and OWNER.fullmatch(parts[0])
    ):
        return OwnedPath(path, parts[0])
    return path


def direct_owner(row):
    if not isinstance(row, dict):
        return None
    subjects = set()
    for obj in (
        row,
        (row.get("receipt") or {}).get("definition")
        if isinstance(row.get("receipt"), dict)
        else None,
        *(
            row.get(key)
            for key in (
                "context",
                "definition",
                "identity",
                "state",
                "request",
                "record",
                "metadata",
                "assignment",
                "consent",
                "operation",
                "slot",
                "taskCenter",
            )
        ),
    ):
        if isinstance(obj, dict):
            value = obj.get("ownerSubject")
            if isinstance(value, str) and OWNER.fullmatch(value):
                subjects.add(value)
    if "ownerUid" in row and isinstance(row["ownerUid"], str):
        subjects.add(owner_key(row["ownerUid"]))
    if len(subjects) > 1:
        from .store import StoreUnavailable

        raise StoreUnavailable
    return next(iter(subjects), None)


def hold_path(owner):
    from .store import document_path

    return document_path(HOLDS, owner)


def index_path(path):
    from .store import document_path

    return document_path(OWNERSHIP, str(path))


def plan_write(unit, path, value):
    from .store import StoreUnavailable

    collection = path.split("/", 1)[0]
    if collection in {HOLDS, OWNERSHIP}:
        raise StoreUnavailable
    if collection in POOLS:
        entries = value.get("entries")
        if not isinstance(entries, dict):
            raise StoreUnavailable
        owners = set()
        previous = (unit.get(path) or {}).get("entries", {})
        for key, entry in entries.items():
            if entry == previous.get(key):
                continue
            if entry.get("ownerSubject") is not None:
                owner = direct_owner(entry)
                if owner is None:
                    raise StoreUnavailable
                owners.add(owner)
        return owners, None
    explicit, scoped = direct_owner(value), getattr(path, "owner", None)
    if explicit is not None and scoped is not None and explicit != scoped:
        raise StoreUnavailable
    owner = scoped or explicit
    if owner is None:
        return {None}, None  # Anonymous/unattributed writes see the global hold count.
    index = None if explicit else (index_path(path), {"ownerSubject": owner, "target": str(path)})
    return {owner}, index


def validate_writes(unit, owners):
    for owner in owners:
        marker = unit.get(hold_path("active-count" if owner is None else owner))
        if marker is not None:
            raise ContractError("authorization_unavailable")


def valid_uid(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or value.strip() != value:
        raise ValueError("Invalid verified subject.")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("Invalid verified subject.")
    return owner_key(value)
