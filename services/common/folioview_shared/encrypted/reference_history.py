"""Bounded, lossless registry-history storage references, without authorization.

Decoded values are ordinary untrusted bundles. Callers must still verify the
complete Root/signature/history chain and all current authorization predicates.
This internal storage format is not a wire DTO and does not change its limits.
"""

import copy
import json
import re

from .constants import (
    CONTRACT_VERSION,
    MAX_READ_BYTES,
    MAX_REGISTRY_BYTES,
    MAX_STORED_DOCUMENT_BYTES,
)
from .errors import ContractError
from .jsonutil import canonical_json, strict_json_loads

REFERENCE_HISTORY_FORMAT = "folioview.reference-history.storage.v1"
_MAX_BUNDLES = 32
_MAX_ENTRIES = 64
_MAX_REFERENCES = _MAX_BUNDLES * _MAX_ENTRIES
_SIGNED_FIELDS = frozenset({"protected", "payload", "signature"})
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+")


def _require(condition: bool) -> None:
    if not condition:
        raise ContractError("malformed_request")


def _size(size: int, maximum: int) -> None:
    if size > maximum:
        raise ContractError("payload_too_large")


def _budget(maximum: int) -> None:
    # Consumers may deduct other row fields, but cannot raise the expanded cap.
    _require(type(maximum) is int and 1 <= maximum <= MAX_READ_BYTES)


def _snapshot(value: object, maximum: int) -> object:
    _size(len(canonical_json(value)), maximum)
    # Preserve numeric types until reference validation: JCS alone would turn
    # 0.0 into 0 and accidentally admit a non-integer reference supplied in a
    # Python mapping. The strict parser creates the owned validation snapshot.
    try:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        # Noncanonical numeric spelling may be longer (notably -0.0 vs 0).
        # This temporary parser bound does not raise either canonical budget:
        # both the source and owned snapshot are checked against `maximum`.
        snapshot = strict_json_loads(raw, max_bytes=4 * maximum)
    except ContractError:
        raise
    except (TypeError, ValueError, RecursionError):
        raise ContractError("malformed_request") from None
    _size(len(canonical_json(snapshot)), maximum)
    return snapshot


def _signed(value: object) -> tuple[str, str, str]:
    # Shape only: do not decode, authenticate, normalize or discard signed bytes.
    _require(type(value) is dict and value.keys() == _SIGNED_FIELDS)
    for name, minimum, maximum in (
        ("protected", 1, 1024),
        ("payload", 1, 699051),
        ("signature", 86, 86),
    ):
        item = value[name]
        _require(
            type(item) is str
            and minimum <= len(item) <= maximum
            and _BASE64URL.fullmatch(item) is not None
        )
    return value["protected"], value["payload"], value["signature"]


def _template(value: object) -> None:
    _require(
        type(value) is dict
        and "entries" not in value
        and {"contractVersion", "checkpoint"} <= value.keys()
        and value["contractVersion"] == CONTRACT_VERSION
    )
    _signed(value["checkpoint"])


def _encode_owned(
    history: list,
    *,
    check_encoded_budget: bool = True,
    history_format: str = REFERENCE_HISTORY_FORMAT,
) -> dict:
    _require(type(history) is list and 1 <= len(history) <= _MAX_BUNDLES)
    certificates, bundles, seen = [], [], {}
    for bundle in history:
        _require(type(bundle) is dict and "entries" in bundle)
        _size(len(canonical_json(bundle)), MAX_REGISTRY_BYTES)
        template = {key: value for key, value in bundle.items() if key != "entries"}
        _template(template)
        entries = bundle["entries"]
        _require(type(entries) is list and 1 <= len(entries) <= _MAX_ENTRIES)
        references = []
        for entry in entries:
            _require(
                type(entry) is dict
                and entry.keys() == {"certificate", "active"}
                and type(entry["active"]) is bool
            )
            key = _signed(entry["certificate"])
            if key not in seen:
                seen[key] = len(certificates)
                certificates.append(entry["certificate"])
            references.append([seen[key], entry["active"]])
        bundles.append({"bundle": template, "entries": references})
    encoded = {
        "format": history_format,
        "certificates": certificates,
        "bundles": bundles,
    }
    if check_encoded_budget:
        _size(len(canonical_json(encoded)), MAX_STORED_DOCUMENT_BYTES)
    return encoded


def encode_reference_history(history: list, *, max_expanded_bytes: int = MAX_READ_BYTES) -> dict:
    """Return detached storage references for a complete, bounded history list.

    ``max_expanded_bytes`` may only tighten the 1 MiB expanded-history ceiling.
    The compact history and the consumer's complete physical document must each
    fit the existing 768 KiB storage ceiling; this helper checks the former only.
    All metadata except the replaced entries is retained without interpreting it.
    """
    _budget(max_expanded_bytes)
    return _encode_owned(_snapshot(history, max_expanded_bytes))


def _decode_owned(
    value: dict, maximum: int, *, history_format: str = REFERENCE_HISTORY_FORMAT
) -> list:
    _require(
        value.keys() == {"format", "certificates", "bundles"} and value["format"] == history_format
    )
    certificates, bundles = value["certificates"], value["bundles"]
    _require(type(certificates) is list and 1 <= len(certificates) <= _MAX_REFERENCES)
    _require(type(bundles) is list and 1 <= len(bundles) <= _MAX_BUNDLES)
    sizes, seen = [], set()
    for certificate in certificates:
        key = _signed(certificate)
        _require(key not in seen)
        seen.add(key)
        sizes.append(len(canonical_json(certificate)))

    used, expanded_size, total_references = set(), 2, 0
    for index, bundle in enumerate(bundles):
        _require(type(bundle) is dict and bundle.keys() == {"bundle", "entries"})
        template, entries = bundle["bundle"], bundle["entries"]
        _template(template)
        _require(type(entries) is list and 1 <= len(entries) <= _MAX_ENTRIES)
        total_references += len(entries)
        _require(total_references <= _MAX_REFERENCES)
        entries_size = 2 + len(entries) - 1
        for pair in entries:
            _require(
                type(pair) is list
                and len(pair) == 2
                and type(pair[0]) is int
                and 0 <= pair[0] < len(certificates)
                and type(pair[1]) is bool
            )
            reference, active = pair
            if reference not in used:
                _require(reference == len(used))
                used.add(reference)
            # Replace the two bytes for {} with the exact original JWS size.
            entries_size += (
                len(canonical_json({"certificate": {}, "active": active})) - 2 + sizes[reference]
            )
        bundle_size = len(canonical_json(template | {"entries": []})) - 2 + entries_size
        _size(bundle_size, MAX_REGISTRY_BYTES)
        expanded_size += bundle_size + (1 if index else 0)
        _size(expanded_size, maximum)
    _require(len(used) == len(certificates))

    # Only after exact UTF-8 accounting succeeds do repeated certificates expand.
    # Each occurrence owns a separate object, including within the same bundle.
    return [
        copy.deepcopy(bundle["bundle"])
        | {
            "entries": [
                {"certificate": copy.deepcopy(certificates[reference]), "active": active}
                for reference, active in bundle["entries"]
            ]
        }
        for bundle in bundles
    ]


def decode_reference_history(
    value: list | dict | bytes, *, max_expanded_bytes: int = MAX_READ_BYTES
) -> list:
    """Return untrusted, independent bundles from legacy or reference storage.

    Legacy lists remain lists and are never migrated or written by this helper.
    Stored bytes must already be canonical JSON, as in the existing Firestore
    representation. Unknown versions, extra wrapper fields and invalid references
    fail closed. Decoding does not verify a signature or confer authorization.
    """
    _budget(max_expanded_bytes)
    if type(value) is bytes:
        parsed = strict_json_loads(value, max_bytes=MAX_STORED_DOCUMENT_BYTES)
        _require(canonical_json(parsed) == value)
        value = parsed
    elif type(value) in (list, dict):
        maximum = max_expanded_bytes if type(value) is list else MAX_STORED_DOCUMENT_BYTES
        value = _snapshot(value, maximum)
    else:
        raise ContractError("malformed_request")
    if type(value) is list:
        _size(len(canonical_json(value)), max_expanded_bytes)
        # Validate legacy shape without requiring a different representation to
        # fit: a valid near-limit legacy value must remain readable as-is.
        _encode_owned(value, check_encoded_budget=False)
        return value
    _require(type(value) is dict)
    return _decode_owned(value, max_expanded_bytes)
