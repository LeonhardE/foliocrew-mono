"""Explicit larger local history views; no wire, storage or authorization grants.

The original storage-v1 API retains its 1 MiB expansion ceiling. Only these named
opt-in operations accept larger local histories, with unchanged encoded limits.
Consumers own complete-row/response budgets and all cryptographic verification.
"""

from .constants import MAX_READ_BYTES, MAX_STORED_DOCUMENT_BYTES
from .jsonutil import canonical_json, strict_json_loads
from .reference_history import (
    REFERENCE_HISTORY_FORMAT,
    _decode_owned,
    _encode_owned,
    _require,
    _snapshot,
    decode_reference_history,
)

STORAGE_HISTORY_V2_FORMAT = "folioview.reference-history.storage.v2"
TRANSPORT_HISTORY_FORMAT = "folioview.reference-history.transport.v1"
# Existing Owner openResult history-list scale: 32 * 131072 + 4096.
# This is a local object ceiling, never a larger HTTP/physical-document budget.
MAX_EXPANDED_HISTORY_BYTES = 4_198_400


def _expanded_budget(maximum: int) -> None:
    _require(type(maximum) is int and 1 <= maximum <= MAX_EXPANDED_HISTORY_BYTES)


def _encode(history: list, maximum: int, history_format: str) -> dict:
    _expanded_budget(maximum)
    _require(type(history) is list)
    return _encode_owned(_snapshot(history, maximum), history_format=history_format)


def encode_storage_history_v2(
    history: list, *, max_expanded_bytes: int = MAX_EXPANDED_HISTORY_BYTES
) -> dict:
    """Encode complete untrusted bundles as explicitly selected storage.v2.

    The compact history still fits 768 KiB. Consumers separately bound the
    complete physical JSON/SDK document and their other logical row fields.
    No legacy input is migrated except by an explicitly committing caller.
    """
    return _encode(history, max_expanded_bytes, STORAGE_HISTORY_V2_FORMAT)


def decode_storage_history_v2(
    value: list | dict | bytes, *, max_expanded_bytes: int = MAX_EXPANDED_HISTORY_BYTES
) -> list:
    """Restore storage.v2, while legacy/v1 retain their original <=1 MiB cap.

    Stored bytes must be canonical strict JSON within 768 KiB. HTTP transport
    objects are deliberately not accepted here. All results remain untrusted.
    """
    _expanded_budget(max_expanded_bytes)
    legacy_maximum = min(max_expanded_bytes, MAX_READ_BYTES)
    if type(value) is list:
        return decode_reference_history(value, max_expanded_bytes=legacy_maximum)
    if type(value) is bytes:
        owned = strict_json_loads(value, max_bytes=MAX_STORED_DOCUMENT_BYTES)
        _require(canonical_json(owned) == value)
        if type(owned) is list:
            return decode_reference_history(owned, max_expanded_bytes=legacy_maximum)
    else:
        _require(type(value) is dict)
        owned = _snapshot(value, MAX_STORED_DOCUMENT_BYTES)
    _require(type(owned) is dict)
    if owned.get("format") == REFERENCE_HISTORY_FORMAT:
        return decode_reference_history(owned, max_expanded_bytes=legacy_maximum)
    return _decode_owned(owned, max_expanded_bytes, history_format=STORAGE_HISTORY_V2_FORMAT)


def encode_transport_history(
    history: list, *, max_expanded_bytes: int = MAX_EXPANDED_HISTORY_BYTES
) -> dict:
    """Return only transport.v1, under the unchanged 768 KiB encoded ceiling.

    This is a service DTO component, not a signed permission or storage object.
    The service must also enforce its complete raw HTTP response byte ceiling.
    """
    return _encode(history, max_expanded_bytes, TRANSPORT_HISTORY_FORMAT)


def decode_transport_history(
    value: dict, *, max_expanded_bytes: int = MAX_EXPANDED_HISTORY_BYTES
) -> list:
    """Decode only a parsed transport.v1 component; never guess another format.

    The caller must perform its original bounded strict HTTP JSON parse first.
    No legacy list, raw bytes or internal storage representation is a fallback.
    """
    _expanded_budget(max_expanded_bytes)
    _require(type(value) is dict)
    owned = _snapshot(value, MAX_STORED_DOCUMENT_BYTES)
    return _decode_owned(owned, max_expanded_bytes, history_format=TRANSPORT_HISTORY_FORMAT)


def snapshot_registry_history(
    history: list, *, max_expanded_bytes: int = MAX_EXPANDED_HISTORY_BYTES
) -> list:
    """Take a typed local copy without conferring trust or a physical budget.

    Validate complete history structure and original per-bundle/count bounds.
    A snapshot may exceed compact storage capacity: a subsequent store or wire
    encoder must independently check that capacity, not infer it from this copy.
    This helper performs no signature, authorization, I/O or storage operation.
    """
    _expanded_budget(max_expanded_bytes)
    _require(type(history) is list)
    owned = _snapshot(history, max_expanded_bytes)
    _encode_owned(owned, check_encoded_budget=False, history_format=STORAGE_HISTORY_V2_FORMAT)
    return owned
