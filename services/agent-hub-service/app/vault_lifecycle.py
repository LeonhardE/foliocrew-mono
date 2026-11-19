"""Root-approved opaque archive maintenance and single-use recovery approvals.

This is a Hub-owned transport profile, not a new shared ControlCommand action.
Only public root proofs, ciphertext digests and immutable receipts are retained.
The owner must already possess the pinned root, through an unlocked archive or
an independently retained recovery copy; Google identity cannot recreate it.
"""

import re
import time

from folioview_shared.encrypted import legacy_archive
from folioview_shared.encrypted.budgets import check_read_response
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import signing_input_fingerprint
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.schema import validate_schema
from folioview_shared.identity import owner_key

from .store import StoreUnavailable, document_path, require_legacy_private_writer
from .vaults import _archive, _current, _fingerprint, identifier

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _digest(value):
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ContractError("malformed_request")


def _history_state(vault, registry, row):
    try:
        return legacy_archive.verify_legacy_archive_history(vault, registry, row)
    except ContractError:
        raise StoreUnavailable from None


def _mutation_response(receipt):
    value = {
        "contractVersion": CONTRACT_VERSION,
        "profile": legacy_archive.PROFILE,
        "receipt": receipt,
    }
    check_read_response(value)
    return value


class VaultLifecycleService:
    def __init__(self, store, *, clock=time.time):
        self.store, self.clock = store, clock

    def now(self):
        value = self.clock()
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise StoreUnavailable
        return int(value)

    @staticmethod
    def _read(unit, owner, vault, now):
        row, registry = _current(unit, owner, now, vault)
        lifecycle = unit.get(document_path("hub_vault_lifecycle", owner, vault))
        return row, registry, lifecycle, _history_state(row, registry, lifecycle)

    def state(self, uid, vault):
        identifier(vault)
        owner = owner_key(uid)

        def read(unit):
            now = self.now()
            row, registry, lifecycle, state = self._read(unit, owner, vault, now)
            pending = state["pending"]
            if pending is not None:
                payload = pending["payload"]
                status = "active"
                if now >= payload["expiresAt"]:
                    status = "expired"
                elif (
                    payload["expectedVaultVersion"] != row["version"]
                    or payload["registrySequence"] != registry.registry_sequence
                    or payload["checkpointDigest"] != registry.checkpoint_digest
                    or payload["keyEpoch"] != registry.key_epoch
                ):
                    status = "stale"
                pending = {
                    "authorizationId": payload["authorizationId"],
                    "newArchiveDigest": payload["newArchiveDigest"],
                    "expiresAt": payload["expiresAt"],
                    "status": status,
                    "command": pending["command"],
                }
            value = {
                "contractVersion": CONTRACT_VERSION,
                "profile": legacy_archive.PROFILE,
                "vaultId": vault,
                "rootKeyId": row["rootKeyId"],
                "vaultVersion": row["version"],
                "registrySequence": registry.registry_sequence,
                "checkpointDigest": registry.checkpoint_digest,
                "keyEpoch": registry.key_epoch,
                "lifecycleVersion": state["version"],
                "archiveRevision": state["revision"],
                "archiveDigest": state["digest"],
                "archive": row["archive"],
                "pendingAuthorization": pending,
                "history": [] if lifecycle is None else lifecycle["history"],
            }
            check_read_response(value)
            return value

        return self.store.transact(read)

    def receipt(self, uid, vault, operation):
        identifier(vault)
        validate_schema("OperationIdentifier", operation)
        owner = owner_key(uid)

        def read(unit):
            _, _, _, state = self._read(unit, owner, vault, self.now())
            item = state["operations"].get(operation)
            if item is None:
                raise ContractError("not_found")
            return _mutation_response(item["receipt"])

        return self.store.transact(read)

    def replace_archive(self, uid, vault, body, operation):
        return self._mutate(uid, vault, body, operation, "archive_replace")

    def delete_archive(self, uid, vault, body, operation):
        return self._mutate(uid, vault, body, operation, "archive_delete")

    def withdraw_deletion(self, uid, vault, body, operation):
        return self._mutate(uid, vault, body, operation, "archive_delete_withdraw")

    def check_deletion(self, uid, vault, body):
        identifier(vault)
        if (
            type(body) is not dict
            or set(body) != {"contractVersion", "command"}
            or body["contractVersion"] != CONTRACT_VERSION
        ):
            raise ContractError("malformed_request")
        owner = owner_key(uid)

        def read(unit):
            row, registry, _, state = self._read(unit, owner, vault, self.now())
            payload = legacy_archive.verify_legacy_archive_command(body["command"], row)
            if payload["action"] != "archive_delete":
                raise ContractError("malformed_request")
            operation = payload["stableOperationId"]
            fingerprint = signing_input_fingerprint(body["command"])
            prior = state["operations"].get(operation)
            withdrawn = state["withdrawn"].get(operation)
            receipt = None
            if prior:
                if prior["receipt"]["commandFingerprint"] != fingerprint:
                    raise ContractError("idempotency_conflict")
                outcome, receipt = "deleted", prior["receipt"]
            elif withdrawn:
                if withdrawn["deletionCommandFingerprint"] != fingerprint:
                    raise ContractError("idempotency_conflict")
                outcome = "withdrawn"
                receipt = state["operations"][withdrawn["stableOperationId"]]["receipt"]
            else:
                counters = {
                    "expectedVaultVersion": row["version"],
                    "expectedLifecycleVersion": state["version"],
                    "expectedArchiveRevision": state["revision"],
                    "registrySequence": registry.registry_sequence,
                    "keyEpoch": registry.key_epoch,
                }
                if any(payload[key] > value for key, value in counters.items()):
                    raise ContractError("version_conflict")
                matches = all(payload[key] == value for key, value in counters.items())
                matches = matches and payload["expectedArchiveDigest"] == state["digest"]
                matches = matches and payload["checkpointDigest"] == registry.checkpoint_digest
                outcome = "unresolved" if matches else "superseded"
            value = {
                "contractVersion": CONTRACT_VERSION,
                "profile": legacy_archive.PROFILE,
                "vaultId": vault,
                "operationId": operation,
                "commandFingerprint": fingerprint,
                "outcome": outcome,
                "vaultVersion": row["version"],
                "lifecycleVersion": state["version"],
                "receipt": receipt,
            }
            check_read_response(value)
            return value

        return self.store.transact(read)

    def authorize_recovery(self, uid, vault, body, operation):
        return self._mutate(uid, vault, body, operation, "recovery_authorize")

    def revoke_recovery(self, uid, vault, authorization_id, body, operation):
        identifier(authorization_id)
        return self._mutate(
            uid, vault, body, operation, "recovery_revoke", authorization_id=authorization_id
        )

    def _mutate(self, uid, vault, body, operation, action, *, authorization_id=None):
        identifier(vault)
        validate_schema("OperationIdentifier", operation)
        fields = {"contractVersion", "command"}
        if action == "archive_replace":
            fields.add("archive")
        if action == "archive_delete_withdraw":
            fields.add("deletionCommand")
        if (
            type(body) is not dict
            or set(body) != fields
            or body["contractVersion"] != CONTRACT_VERSION
        ):
            raise ContractError("malformed_request")
        owner = owner_key(uid)

        def update(unit):
            row, registry, lifecycle, state = self._read(unit, owner, vault, self.now())
            payload = legacy_archive.verify_legacy_archive_command(body["command"], row)
            if payload["action"] != action:
                raise ContractError("malformed_request")
            if payload["stableOperationId"] != operation:
                raise ContractError("idempotency_conflict")
            if authorization_id is not None and payload["authorizationId"] != authorization_id:
                raise ContractError("recipient_binding_mismatch")
            if action == "archive_replace":
                _archive(body["archive"], owner=owner, vault=vault, root=row["rootKeyId"])
                if _fingerprint(body["archive"]) != payload["newArchiveDigest"]:
                    raise ContractError("recipient_binding_mismatch")
            if action == "archive_delete_withdraw":
                original = legacy_archive.verify_legacy_archive_command(
                    body["deletionCommand"], row
                )
                if (
                    original["action"] != "archive_delete"
                    or original["stableOperationId"] != payload["deletionOperationId"]
                    or original["expectedLifecycleVersion"] != payload["deletionLifecycleVersion"]
                    or signing_input_fingerprint(body["deletionCommand"])
                    != payload["deletionCommandFingerprint"]
                ):
                    raise ContractError("recipient_binding_mismatch")
            prior = state["operations"].get(operation)
            if prior is not None:
                if (
                    signing_input_fingerprint(body["command"])
                    != prior["receipt"]["commandFingerprint"]
                ):
                    raise ContractError("idempotency_conflict")
                # A receipt is an immutable fact, not permission to restore old state.
                return _mutation_response(prior["receipt"])
            if state["version"] >= legacy_archive.MAX_LIFECYCLE_OPERATIONS:
                raise ContractError("version_conflict")
            if payload["expectedVaultVersion"] != row["version"]:
                raise ContractError("version_conflict")
            if (
                payload["registrySequence"] != registry.registry_sequence
                or payload["checkpointDigest"] != registry.checkpoint_digest
                or payload["keyEpoch"] != registry.key_epoch
            ):
                raise ContractError("registry_conflict")
            if action == "archive_replace":
                archive = body["archive"]
                old = row["archive"]
                if old is None:
                    if payload["mode"] != "recovery":
                        raise ContractError("key_authorization_required")
                else:
                    if archive["iv"] == old["iv"] or archive["ciphertext"] == old["ciphertext"]:
                        raise ContractError("recipient_binding_mismatch")
                    if payload["mode"] == "rewrap":
                        if archive["credentialId"] != old["credentialId"]:
                            raise ContractError("recipient_binding_mismatch")
                    elif (
                        archive["credentialId"] == old["credentialId"]
                        or archive["prfSalt"] == old["prfSalt"]
                    ):
                        raise ContractError("recipient_binding_mismatch")
            now = self.now()
            advanced = legacy_archive.advance_legacy_archive(state, payload, body["command"], now)
            receipt = legacy_archive.legacy_archive_receipt(
                row, payload, advanced, body["command"], now
            )
            item = {"command": body["command"], "receipt": receipt}
            next_lifecycle = {
                "ownerSubject": owner,
                "vaultId": vault,
                "rootKeyId": row["rootKeyId"],
                "initialArchiveDigest": state["digest"]
                if lifecycle is None
                else lifecycle["initialArchiveDigest"],
                "history": [*([] if lifecycle is None else lifecycle["history"]), item],
            }
            response = _mutation_response(receipt)
            require_legacy_private_writer(unit, owner)
            # Firestore reads are complete before either buffered write is flushed.
            if action in {"archive_replace", "archive_delete"}:
                archive = body["archive"] if action == "archive_replace" else None
                next_row = {**row, "archive": archive}
                _history_state(next_row, registry, next_lifecycle)
                unit.put(document_path("hub_vaults", owner), next_row)
            unit.put(document_path("hub_vault_lifecycle", owner, vault), next_lifecycle)
            return response

        return self.store.transact(update)
