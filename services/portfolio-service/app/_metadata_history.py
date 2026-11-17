"""Private metadata-only reuse of exact, fully verified public history snapshots."""

import copy
import hashlib
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from threading import Lock

from folioview_shared.encrypted.authority import (
    RegistryCertificateMemo,
    VerifiedRegistry,
    verify_registry,
)
from folioview_shared.encrypted.constants import MAX_SAFE_INTEGER
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json

_MAX_ENTRIES = 8
_MAX_LOGICAL_BYTES = 4 * 1024 * 1024


def _now(value):
    if type(value) is not int or not 0 <= value <= MAX_SAFE_INTEGER:
        raise ContractError("malformed_request")


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _weight(registry, key):
    # The same logical charge as the original candidate, without serializing
    # every certificate both inside the state and again as a private payload.
    certificate_sizes = [
        (len(canonical_json(kid)), len(canonical_json(_plain(cert))))
        for kid, cert in registry.certificates.items()
    ]
    state = {
        "owner": registry.owner_subject,
        "vault": registry.vault_id,
        "root": registry.root_key_id,
        "rootEpoch": registry.root_epoch,
        "sequence": registry.registry_sequence,
        "keyEpoch": registry.key_epoch,
        "checkpoint": registry.checkpoint_digest,
        "issuedAt": registry.issued_at,
        "certificates": None,
        "active": sorted(registry.active_key_ids),
        "revoked": sorted(registry.revoked_key_ids),
        "checkpoints": [
            [sequence, digest] for sequence, digest in registry.checkpoint_history.items()
        ],
        "localEpochs": [
            [list(identity), epoch] for identity, epoch in registry.local_key_epochs.items()
        ],
    }
    # Replace the four bytes of null with the original canonical object size.
    certificates_bytes = 2 + sum(kid + 1 + cert for kid, cert in certificate_sizes)
    certificates_bytes += max(0, len(certificate_sizes) - 1)
    return (
        len(canonical_json(state))
        - 4
        + certificates_bytes
        + sum(size + 43 for _, size in certificate_sizes)
        + sum(len(item) if type(item) is bytes else len(item.encode("utf-8")) for item in key)
    )


def _owned_inputs():
    # The seal is closure-owned, not a constructor argument or module-global
    # token. The only factory always clones; no API adopts caller-owned rows.
    seal = object()

    class OwnedAuthority:
        __slots__ = ("__row", "__key", "__seal", "__running", "__used")

        def __new__(cls):
            raise TypeError("Owned metadata input is created only by its cloning factory.")

        def __setattr__(self, name, value):
            raise AttributeError("Owned metadata input is immutable.")

        def __delattr__(self, name):
            raise AttributeError("Owned metadata input is immutable.")

        def _check(self):
            if (
                getattr(self, "_OwnedAuthority__seal", None) is not seal
                or self.__used
                or not self.__running
            ):
                raise ContractError("malformed_request")

        def _owns(self, document):
            self._check()
            return document is self.__row

        def _key(self):
            self._check()
            if self.__key is None:
                row = self.__row
                key = (
                    "portfolio-metadata-history.v1",
                    row["ownerSubject"],
                    row["vaultId"],
                    row["rootKeyId"],
                    canonical_json(row["rootJwk"]),
                    hashlib.sha256(canonical_json(row["registryHistory"])).digest(),
                )
                object.__setattr__(self, "_OwnedAuthority__key", key)
            return self.__key

        def _verified(self, now):
            self._check()
            row = self.__row
            history = row["registryHistory"]
            if type(history) is not list or not 1 <= len(history) <= 32:
                raise ContractError("malformed_request")
            registry = None
            signatures = RegistryCertificateMemo()
            for bundle in history:
                registry = verify_registry(
                    bundle,
                    root_jwk=row["rootJwk"],
                    pinned_root_key_id=row["rootKeyId"],
                    owner_subject=row["ownerSubject"],
                    vault_id=row["vaultId"],
                    now=now,
                    previous=registry,
                    signature_memo=signatures,
                )
            return registry

        def __run(self, operation):
            if (
                getattr(self, "_OwnedAuthority__seal", None) is not seal
                or self.__used
                or self.__running
            ):
                raise ContractError("malformed_request")
            object.__setattr__(self, "_OwnedAuthority__running", True)
            try:
                return operation()
            finally:
                # Authority.document becomes visible only after this input is
                # consumed. It can never be reused with a cached earlier key.
                object.__setattr__(self, "_OwnedAuthority__used", True)
                object.__setattr__(self, "_OwnedAuthority__running", False)
                object.__setattr__(self, "_OwnedAuthority__row", None)
                object.__setattr__(self, "_OwnedAuthority__key", None)

        def _authorize(self, owner, source, now, proofs, registry_cache):
            from .holdings import _authority

            return self.__run(
                lambda: _authority(
                    self.__row,
                    owner,
                    source,
                    now,
                    registry_cache=registry_cache,
                    metadata_history_proofs=proofs,
                    owned_authority=self,
                )
            )

        def _registry(self, proofs, now):
            if type(proofs) is not _MetadataHistoryProofs:
                raise ContractError("malformed_request")
            return self.__run(lambda: proofs._resolve(self, now))

    def own(value):
        document = copy.deepcopy(value)
        value = object.__new__(OwnedAuthority)
        for field, item in (
            ("row", document),
            ("key", None),
            ("seal", seal),
            ("running", False),
            ("used", False),
        ):
            object.__setattr__(value, "_OwnedAuthority__" + field, item)
        return value

    return OwnedAuthority, own


_OwnedAuthority, _own_authority = _owned_inputs()
del _owned_inputs


def _attempt_inputs():
    seal = object()

    class MetadataAttempt:
        __slots__ = ("__seal", "__registries")

        def __new__(cls):
            raise TypeError("Metadata attempts are created only empty by their factory.")

        def __setattr__(self, name, value):
            raise AttributeError("Metadata attempt state is private.")

        def __delattr__(self, name):
            raise AttributeError("Metadata attempt state is private.")

        def _resolve(self, proofs, owned, now):
            if (
                getattr(self, "_MetadataAttempt__seal", None) is not seal
                or type(proofs) is not _MetadataHistoryProofs
                or type(owned) is not _OwnedAuthority
            ):
                raise ContractError("malformed_request")
            _now(now)
            key = owned._key()
            registry = self.__registries.get(key)
            if registry is None:
                registry = proofs._resolve(owned, now)
                self.__registries[key] = registry
            if registry.issued_at > now:
                raise ContractError("registry_conflict")
            return replace(registry)

    def attempt():
        value = object.__new__(MetadataAttempt)
        object.__setattr__(value, "_MetadataAttempt__seal", seal)
        object.__setattr__(value, "_MetadataAttempt__registries", {})
        return value

    return MetadataAttempt, attempt


_MetadataAttempt, _metadata_attempt = _attempt_inputs()
del _attempt_inputs


@dataclass(frozen=True)
class _Entry:
    registry: VerifiedRegistry
    weight: int


class _MetadataHistoryProofs:
    """Bounded exact static proofs; only the owned full verifier publishes.

    Content identity, fresh row checks and current time determine validity; LRU
    limits bound retention without a permission TTL or a new request quota.
    """

    __slots__ = ("__entries", "__lock", "__size")

    def __init__(self):
        self.__entries = OrderedDict()
        self.__lock = Lock()
        self.__size = 0

    def _attempt(self):
        return _metadata_attempt()

    def _verify(self, history, *, root_jwk, root_key_id, owner, vault, now):
        # Defensive standalone seam also goes through the same owning factory;
        # it accepts complete signed inputs, never a VerifiedRegistry to insert.
        owned = _own_authority(
            {
                "registryHistory": history,
                "rootJwk": root_jwk,
                "rootKeyId": root_key_id,
                "ownerSubject": owner,
                "vaultId": vault,
            }
        )
        return owned._registry(self, now)

    def _resolve(self, owned, now):
        _now(now)
        if type(owned) is not _OwnedAuthority:
            raise ContractError("malformed_request")
        key = owned._key()
        with self.__lock:
            cached = self.__entries.get(key)
            if cached is not None:
                self.__entries.move_to_end(key)
        if cached is not None:
            if cached.registry.issued_at > now:
                raise ContractError("registry_conflict")
            return replace(cached.registry)

        registry = owned._verified(now)
        weight = _weight(registry, key)
        if weight <= _MAX_LOGICAL_BYTES:
            # Pure verification/clone/weight work is outside the lock.
            with self.__lock:
                if key not in self.__entries:
                    while self.__entries and (
                        len(self.__entries) >= _MAX_ENTRIES
                        or self.__size + weight > _MAX_LOGICAL_BYTES
                    ):
                        _, old = self.__entries.popitem(last=False)
                        self.__size -= old.weight
                    self.__entries[key] = _Entry(registry, weight)
                    self.__size += weight
        return replace(registry)


# get_service() intentionally creates a fresh PortfolioService for every HTTP
# dependency. Only exact static public proofs live at process scope: no Service,
# Store, database row or current authorization result is retained here.
_PROCESS_HISTORY_PROOFS = _MetadataHistoryProofs()


def _metadata_history_proofs():
    return _PROCESS_HISTORY_PROOFS
