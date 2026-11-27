"""Root-approved successor owner certificates plus one atomic opaque archive rewrap.

Certificate payloads and shared registry verification stay immutable. No private
key is accepted here; a later trusted client must retain historical reader keys.
"""

import math
import time

from folioview_shared.encrypted import legacy_archive
from folioview_shared.encrypted.authority import verify_registry
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import signing_input_fingerprint
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.key_renewal import (
    MAX_CERTIFICATE_SECONDS as MAX_CERTIFICATE_SECONDS,
)
from folioview_shared.encrypted.key_renewal import (
    PROFILE,
    owner_renewal_state,
)
from folioview_shared.encrypted.key_renewal import (
    owner_renewal_receipt as _receipt,
)
from folioview_shared.encrypted.key_renewal import (
    owner_renewal_response as _result,
)
from folioview_shared.encrypted.key_renewal import (
    require_fresh_renewal_keys as _fresh_keys,
)
from folioview_shared.encrypted.key_renewal import (
    verify_owner_renewal_archive as _commands,
)
from folioview_shared.encrypted.key_renewal import (
    verify_owner_renewal_command as _payload,
)
from folioview_shared.encrypted.key_renewal import (
    verify_owner_renewal_delta as _delta,
)
from folioview_shared.encrypted.schema import validate_schema
from folioview_shared.identity import owner_key

from .store import StoreUnavailable, document_path, require_legacy_private_writer
from .vault_lifecycle import VaultLifecycleService, _history_state
from .vaults import (
    MAX_HISTORY,
    _archive,
    _fingerprint,
    _verify_row,
    capacity_exhausted,
    identifier,
    positive,
)

_RECORD_FIELDS = frozenset(
    {"profile", "ownerSubject", "vaultId", "rootKeyId", "command", "archiveCommand", "receipt"}
)


def _registries(row, now):
    result = []
    for bundle in row["registryHistory"]:
        result.append(
            verify_registry(
                bundle,
                root_jwk=row["rootJwk"],
                pinned_root_key_id=row["rootKeyId"],
                owner_subject=row["ownerSubject"],
                vault_id=row["vaultId"],
                now=now,
                previous=result[-1] if result else None,
            )
        )
    return result


class VaultKeyRenewalService:
    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock

    def now(self):
        value = self.clock()
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or (isinstance(value, float) and not math.isfinite(value))
            or value < 0
        ):
            raise StoreUnavailable
        return int(value)

    @staticmethod
    def _path(owner, operation):
        return document_path("hub_operations", owner, "key-renewal", operation)

    def state(self, uid, vault):
        identifier(vault)
        owner = owner_key(uid)

        def read(unit):
            now = self.now()
            row, registry, _, state = VaultLifecycleService._read(unit, owner, vault, now)
            return owner_renewal_state(row, registry, state, now)

        return self.store.transact(read)

    def _stored(self, saved, row, state, registries, operation):
        try:
            if (
                type(saved) is not dict
                or set(saved) != _RECORD_FIELDS
                or saved["profile"] != PROFILE
                or any(saved[f] != row[f] for f in ("ownerSubject", "vaultId", "rootKeyId"))
            ):
                raise StoreUnavailable
            p = _payload(saved["command"], row)
            ap = _commands(p, saved["archiveCommand"], row)
            if p["stableOperationId"] != operation or not 1 <= p["registrySequence"] < len(
                registries
            ):
                raise StoreUnavailable
            at = saved["receipt"]["acceptedAt"]
            positive(at, zero=True)
            if not (
                p["issuedAt"] <= at < p["expiresAt"] and ap["issuedAt"] <= at < ap["expiresAt"]
            ):
                raise StoreUnavailable
            previous, next_registry = registries[
                p["registrySequence"] - 1 : p["registrySequence"] + 1
            ]
            _fresh_keys(p, registries[: p["registrySequence"]])
            _delta(p, previous, next_registry, at)
            item = state["operations"].get(operation)
            if (
                item is None
                or signing_input_fingerprint(item["command"]) != p["archiveCommandFingerprint"]
                or item["receipt"]["acceptedAt"] != at
            ):
                raise StoreUnavailable
            expected_state = {
                "version": item["receipt"]["lifecycleVersion"],
                "revision": item["receipt"]["archiveRevision"],
                "digest": item["receipt"]["archiveDigest"],
            }
            if saved["receipt"] != _receipt(
                row, p, next_registry, expected_state, saved["command"], at
            ):
                raise StoreUnavailable
            return p, _result(saved["receipt"])
        except (ContractError, KeyError, TypeError, ValueError, IndexError):
            raise StoreUnavailable from None

    def receipt(self, uid, vault, operation):
        identifier(vault)
        validate_schema("OperationIdentifier", operation)
        owner = owner_key(uid)

        def read(unit):
            now = self.now()
            row, _, _, state = VaultLifecycleService._read(unit, owner, vault, now)
            saved = unit.get(self._path(owner, operation))
            if saved is None:
                raise ContractError("not_found")
            return self._stored(saved, row, state, _registries(row, now), operation)[1]

        return self.store.transact(read)

    def renew(self, uid, vault, body, operation):
        identifier(vault)
        validate_schema("OperationIdentifier", operation)
        if (
            type(body) is not dict
            or set(body)
            != {"contractVersion", "registryBundle", "archive", "command", "archiveCommand"}
            or body["contractVersion"] != CONTRACT_VERSION
        ):
            raise ContractError("malformed_request")
        owner = owner_key(uid)

        def update(unit):
            now = self.now()
            row, current, lifecycle, state = VaultLifecycleService._read(unit, owner, vault, now)
            p = _payload(body["command"], row)
            ap = _commands(p, body["archiveCommand"], row)
            if p["stableOperationId"] != operation:
                raise ContractError("idempotency_conflict")
            _archive(body["archive"], owner=owner, vault=vault, root=row["rootKeyId"])
            if _fingerprint(body["archive"]) != p["newArchiveDigest"]:
                raise ContractError("recipient_binding_mismatch")
            saved = unit.get(self._path(owner, operation))
            registries = _registries(row, now)
            if saved is not None:
                prior, response = self._stored(saved, row, state, registries, operation)
                if (
                    signing_input_fingerprint(body["command"])
                    != signing_input_fingerprint(saved["command"])
                    or p["archiveCommandFingerprint"] != prior["archiveCommandFingerprint"]
                ):
                    raise ContractError("idempotency_conflict")
                previous = registries[p["registrySequence"] - 1]
                proposed = verify_registry(
                    body["registryBundle"],
                    root_jwk=row["rootJwk"],
                    pinned_root_key_id=row["rootKeyId"],
                    owner_subject=owner,
                    vault_id=vault,
                    now=now,
                    previous=previous,
                )
                _delta(p, previous, proposed, saved["receipt"]["acceptedAt"])
                return response
            if operation in state["operations"]:
                raise ContractError("idempotency_conflict")
            if row["version"] != p["expectedVaultVersion"]:
                raise ContractError("version_conflict")
            if (
                p["registrySequence"] != current.registry_sequence
                or p["checkpointDigest"] != current.checkpoint_digest
                or p["keyEpoch"] != current.key_epoch
            ):
                raise ContractError("registry_conflict")
            if (
                p["expectedLifecycleVersion"] != state["version"]
                or p["expectedArchiveRevision"] != state["revision"]
                or p["expectedArchiveDigest"] != state["digest"]
            ):
                raise ContractError("version_conflict")
            if state["pending"] is not None or state["deleted"]:
                raise ContractError("key_authorization_required")
            if (
                len(row["registryHistory"]) >= MAX_HISTORY
                or capacity_exhausted(row)
                or state["version"] >= legacy_archive.MAX_LIFECYCLE_OPERATIONS
            ):
                raise ContractError("version_conflict")
            proposed = verify_registry(
                body["registryBundle"],
                root_jwk=row["rootJwk"],
                pinned_root_key_id=row["rootKeyId"],
                owner_subject=owner,
                vault_id=vault,
                now=now,
                previous=current,
            )
            _fresh_keys(p, registries)
            _delta(p, current, proposed, now)
            old, new = row["archive"], body["archive"]
            if any(new[f] != old[f] for f in ("credentialId", "prfSalt")) or any(
                new[f] == old[f] for f in ("iv", "ciphertext")
            ):
                raise ContractError("recipient_binding_mismatch")
            next_row = {
                **row,
                "archive": new,
                "registryHistory": [*row["registryHistory"], body["registryBundle"]],
                "version": row["version"] + 1,
                "operationCount": row["operationCount"] + 1,
            }
            _verify_row(next_row, owner, now)
            advanced = legacy_archive.advance_legacy_archive(state, ap, body["archiveCommand"], now)
            ar = legacy_archive.legacy_archive_receipt(
                row, ap, advanced, body["archiveCommand"], now
            )
            next_lifecycle = {
                "ownerSubject": owner,
                "vaultId": vault,
                "rootKeyId": row["rootKeyId"],
                "initialArchiveDigest": state["digest"]
                if lifecycle is None
                else lifecycle["initialArchiveDigest"],
                "history": [
                    *([] if lifecycle is None else lifecycle["history"]),
                    {"command": body["archiveCommand"], "receipt": ar},
                ],
            }
            _history_state(next_row, proposed, next_lifecycle)
            # All signatures/history and buffered-read work finish before the final
            # clock fence. Rebuild only the final acceptance timestamp afterwards.
            accepted_at = self.now()
            if not (
                now <= accepted_at
                and p["issuedAt"] <= accepted_at < p["expiresAt"]
                and ap["issuedAt"] <= accepted_at < ap["expiresAt"]
            ):
                raise ContractError("key_authorization_required")
            _delta(p, current, proposed, accepted_at)
            advanced = legacy_archive.advance_legacy_archive(
                state, ap, body["archiveCommand"], accepted_at
            )
            next_lifecycle["history"][-1]["receipt"] = legacy_archive.legacy_archive_receipt(
                row, ap, advanced, body["archiveCommand"], accepted_at
            )
            receipt = _receipt(row, p, proposed, advanced, body["command"], accepted_at)
            response = _result(receipt)
            record = {
                "profile": PROFILE,
                "ownerSubject": owner,
                "vaultId": vault,
                "rootKeyId": row["rootKeyId"],
                "command": body["command"],
                "archiveCommand": body["archiveCommand"],
                "receipt": receipt,
            }
            require_legacy_private_writer(unit, owner)
            unit.put(document_path("hub_vaults", owner), next_row)
            unit.put(document_path("hub_vault_lifecycle", owner, vault), next_lifecycle)
            unit.put(self._path(owner, operation), record)
            return response

        return self.store.transact(update)
