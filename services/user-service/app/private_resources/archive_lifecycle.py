"""Retained signed archive lifecycle and exact receipts after the same-Root handover."""

import time

from pydantic import ValidationError

from folioview_shared.encrypted.budgets import check_read_response
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.crypto import signing_input_fingerprint
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json, strict_json_loads
from folioview_shared.encrypted.legacy_archive import (
    MAX_LIFECYCLE_OPERATIONS,
    advance_legacy_archive,
    archive_deletion_outcome,
    legacy_archive_receipt,
    validate_passkey_archive,
    verify_legacy_archive_command,
    verify_transferred_archive_history,
)
from folioview_shared.encrypted.legacy_archive import PROFILE as LIFECYCLE_PROFILE
from folioview_shared.encrypted.private_resources import PrivateRegistryCursor
from folioview_shared.identity import owner_key

from ..resources import ResourceUnavailable, SQLiteUserResourceStore
from .authority_cutover import ARCHIVE_RECORDS, UserAuthorityCutover
from .legacy_baselines import _sha
from .recovery import COLLECTION as HEADS
from .recovery import CurrentHead
from .source_registrations import _matches_current, current_registry

PROFILE = "folioview.owner-user-archive-lifecycle.v1"
_MUTATIONS = {"archive_replace", "recovery_authorize", "recovery_revoke"}


class PrivateArchiveLifecycle:
    def __init__(self, store, *, clock=time.time):
        self.cutover = UserAuthorityCutover(store)
        self.clock = clock
        if isinstance(store, SQLiteUserResourceStore):
            with store.connection() as db:
                db.execute(
                    f"CREATE TABLE IF NOT EXISTS {ARCHIVE_RECORDS} "
                    "(owner TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )

    @staticmethod
    def _boundary(state):
        return {
            "state": "deleted" if state["deleted"] else "active",
            "version": state["version"] + 1,
            "digest": state["digest"],
        }

    def _snapshot(self, uid, vault, now):
        self.cutover._named_store()
        owner = owner_key(uid)
        head, row = self.cutover._read(((HEADS, owner), (ARCHIVE_RECORDS, owner)))
        if head is None:
            raise ContractError("not_found")
        decoded = CurrentHead.model_validate(head)
        if (decoded.ownerSubject, decoded.vaultId) != (owner, vault) or decoded.handover is None:
            raise ContractError("not_found")
        original = self.cutover.verifier.baselines.read(
            owner, vault, decoded.handover.baselineDigest
        )
        if original is None:
            raise ContractError("authorization_unavailable")
        original = strict_json_loads(original)
        if (original["ownerSubject"], original["vaultId"], original["rootKeyId"]) != (
            owner,
            vault,
            decoded.rootKeyId,
        ):
            raise ContractError("authorization_unavailable")
        _, before, old_bundles = self.cutover.verifier.original_history(original, now)
        evidence, registry, current_bundles = current_registry(
            self.cutover, uid, vault, now, allow_deleted=True
        )
        if not _matches_current(head, evidence):
            raise ContractError("version_conflict")
        original_lifecycle = original["archiveLifecycle"]
        current_archive = original["archive"]
        lifecycle = original_lifecycle
        if row is not None:
            if (
                type(row) is not dict
                or set(row) != {"archive", "lifecycle", "baselineDigest"}
                or row["baselineDigest"] != decoded.handover.baselineDigest
                or type(row["lifecycle"]) is not dict
            ):
                raise ContractError("authorization_unavailable")
            lifecycle = row["lifecycle"]
            if original_lifecycle is not None and (
                original_lifecycle["initialArchiveDigest"] != lifecycle.get("initialArchiveDigest")
                or lifecycle.get("history", [])[: before["version"]]
                != original_lifecycle["history"]
            ):
                raise ContractError("authorization_unavailable")
            if (
                original_lifecycle is None
                and lifecycle.get("initialArchiveDigest") != before["digest"]
            ):
                raise ContractError("authorization_unavailable")
            current_archive = row["archive"]
        vault_info = {
            "ownerSubject": owner,
            "vaultId": vault,
            "rootKeyId": decoded.rootKeyId,
            "rootJwk": original["rootJwk"],
            "archive": current_archive,
            "version": decoded.vaultVersion,
            "registryHistory": [*old_bundles, *current_bundles],
        }
        cursor = PrivateRegistryCursor(registry, decoded.registry.registryEpoch)
        state = (
            verify_transferred_archive_history(vault_info, cursor, lifecycle)
            if row is not None
            else before
        )
        if row is not None:
            start = evidence["registryStart"]["registrySequence"]
            for entry in lifecycle["history"][before["version"] :]:
                command = verify_legacy_archive_command(entry["command"], vault_info)
                if command["registrySequence"] < start:
                    raise ContractError("authorization_unavailable")
        if decoded.archive.model_dump() != self._boundary(state):
            raise ContractError("authorization_unavailable")
        return head, row, vault_info, cursor, state, lifecycle, old_bundles

    def read(self, uid, vault, nonce, operation):
        owner = owner_key(uid)
        try:
            now = int(self.clock())
            raw, row, vault_info, cursor, state, lifecycle, bundles = self._snapshot(
                uid, vault, now
            )
            head = CurrentHead.model_validate(raw)
            if self.cutover._read(((HEADS, owner), (ARCHIVE_RECORDS, owner))) != [raw, row]:
                raise ContractError("version_conflict")
            history = [] if lifecycle is None else lifecycle["history"]
            pending = state["pending"]
            authorization = None
            if pending is not None:
                payload = pending["payload"]
                status = "active"
                if now >= payload["expiresAt"]:
                    status = "expired"
                elif (
                    payload["expectedVaultVersion"] != head.vaultVersion
                    or payload["registrySequence"] != cursor.registry.registry_sequence
                    or payload["checkpointDigest"] != cursor.registry.checkpoint_digest
                    or payload["keyEpoch"] != head.registry.keyEpoch
                ):
                    status = "stale"
                authorization = {
                    "authorizationId": payload["authorizationId"],
                    "newArchiveDigest": payload["newArchiveDigest"],
                    "expiresAt": payload["expiresAt"],
                    "status": status,
                    "command": pending["command"],
                }
            result = {
                "contractVersion": CONTRACT_VERSION,
                "profile": PROFILE,
                "ownerSubject": owner,
                "vaultId": vault,
                "rootKeyId": head.rootKeyId,
                "nonce": nonce,
            }
            if operation is not None:
                item = state["operations"].get(operation)
                if item is None:
                    raise ContractError("not_found")
                result.update(operationId=operation, receipt=item["receipt"])
            else:
                result.update(
                    state={
                        "contractVersion": CONTRACT_VERSION,
                        "profile": LIFECYCLE_PROFILE,
                        "vaultId": vault,
                        "rootKeyId": head.rootKeyId,
                        "vaultVersion": head.vaultVersion,
                        "registrySequence": head.registry.registrySequence,
                        "checkpointDigest": head.registry.checkpointDigest,
                        "keyEpoch": head.registry.keyEpoch,
                        "lifecycleVersion": state["version"],
                        "archiveRevision": state["revision"],
                        "archiveDigest": state["digest"],
                        "archive": vault_info["archive"],
                        "pendingAuthorization": authorization,
                        "history": history,
                    },
                    originalCheckpoints=[bundle["checkpoint"] for bundle in bundles]
                    if history
                    else [],
                )
            check_read_response(result)
            return result
        except ResourceUnavailable as error:
            if isinstance(error.__cause__, ContractError):
                raise error.__cause__ from None
        except (KeyError, ValidationError, TypeError):
            pass
        raise ContractError("authorization_unavailable")

    def check_removal(self, uid, vault, operation, command):
        head, row, vault_info, cursor, state, _, _ = self._snapshot(uid, vault, int(self.clock()))
        result = archive_deletion_outcome(vault_info, cursor.registry, state, command)
        if result["operationId"] != operation:
            raise ContractError("idempotency_conflict")
        owner = owner_key(uid)
        if self.cutover._read(((HEADS, owner), (ARCHIVE_RECORDS, owner))) != [head, row]:
            raise ContractError("version_conflict")
        return result

    def advance(
        self, uid, vault, operation, command, archive, *, removal_action=None, deletion=None
    ):
        owner = owner_key(uid)
        try:
            now = int(self.clock())
            head, previous, vault_info, cursor, state, lifecycle, _ = self._snapshot(
                uid, vault, now
            )
            payload = verify_legacy_archive_command(command, vault_info)
            action = payload["action"]
            if (
                (action not in _MUTATIONS if removal_action is None else action != removal_action)
                or (action == "archive_replace") != (archive is not None)
                or (action == "archive_delete_withdraw") != (deletion is not None)
            ):
                raise ContractError("malformed_request")
            if deletion is not None:
                original = verify_legacy_archive_command(deletion, vault_info)
                if (
                    original["action"] != "archive_delete"
                    or original["stableOperationId"] != payload["deletionOperationId"]
                    or original["expectedLifecycleVersion"] != payload["deletionLifecycleVersion"]
                    or signing_input_fingerprint(deletion) != payload["deletionCommandFingerprint"]
                ):
                    raise ContractError("recipient_binding_mismatch")
            if payload["stableOperationId"] != operation:
                raise ContractError("idempotency_conflict")
            if action == "archive_replace":
                validate_passkey_archive(
                    archive, owner=owner, vault=vault, root=vault_info["rootKeyId"]
                )
                if _sha(canonical_json(archive)) != payload["newArchiveDigest"]:
                    raise ContractError("recipient_binding_mismatch")
            prior = state["operations"].get(operation)
            if prior is not None:
                if prior["receipt"]["commandFingerprint"] != signing_input_fingerprint(command):
                    raise ContractError("idempotency_conflict")
                return prior["receipt"]
            if (
                state["version"] >= MAX_LIFECYCLE_OPERATIONS
                or payload["expectedVaultVersion"] != vault_info["version"]
            ):
                raise ContractError("version_conflict")
            registry = cursor.registry
            if (
                payload["registrySequence"] != registry.registry_sequence
                or payload["checkpointDigest"] != registry.checkpoint_digest
                or payload["keyEpoch"] != registry.key_epoch
            ):
                raise ContractError("registry_conflict")
            current_archive = vault_info["archive"]
            if action == "archive_replace":
                if current_archive is None:
                    if payload["mode"] != "recovery":
                        raise ContractError("key_authorization_required")
                else:
                    if (
                        archive["iv"] == current_archive["iv"]
                        or archive["ciphertext"] == current_archive["ciphertext"]
                    ):
                        raise ContractError("recipient_binding_mismatch")
                    if payload["mode"] == "rewrap":
                        if archive["credentialId"] != current_archive["credentialId"]:
                            raise ContractError("recipient_binding_mismatch")
                    elif (
                        archive["credentialId"] == current_archive["credentialId"]
                        or archive["prfSalt"] == current_archive["prfSalt"]
                    ):
                        raise ContractError("recipient_binding_mismatch")
                current_archive = archive
            elif action == "archive_delete":
                current_archive = None
            after = advance_legacy_archive(state, payload, command, now)
            receipt = legacy_archive_receipt(vault_info, payload, after, command, now)
            retained = [] if lifecycle is None else lifecycle["history"]
            next_lifecycle = {
                "ownerSubject": owner,
                "vaultId": vault,
                "rootKeyId": vault_info["rootKeyId"],
                "initialArchiveDigest": state["digest"]
                if lifecycle is None
                else lifecycle["initialArchiveDigest"],
                "history": [*retained, {"command": command, "receipt": receipt}],
            }
            new_vault = {**vault_info, "archive": current_archive}
            verify_transferred_archive_history(new_vault, cursor, next_lifecycle)
            next_record = {
                "archive": current_archive,
                "lifecycle": next_lifecycle,
                "baselineDigest": head["handover"]["baselineDigest"],
            }
            cells = ((HEADS, owner), (ARCHIVE_RECORDS, owner))
            next_head = {**head, "archive": self._boundary(after)}

            def commit(read, write):
                if read(cells) != [head, previous]:
                    raise ContractError("version_conflict")
                write({cells[0]: next_head, cells[1]: next_record})
                return receipt

            return self.cutover._transaction(
                commit, writes=True, replace=cells if previous is not None else cells[:1]
            )
        except ResourceUnavailable as error:
            if isinstance(error.__cause__, ContractError):
                raise error.__cause__ from None
        except (KeyError, ValidationError, TypeError):
            pass
        raise ContractError("authorization_unavailable")
