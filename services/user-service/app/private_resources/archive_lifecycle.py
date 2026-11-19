"""Retained signed archive lifecycle and exact receipts after the same-Root handover."""

import time

from pydantic import ValidationError

from folioview_shared.encrypted.budgets import check_read_response
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import strict_json_loads
from folioview_shared.encrypted.legacy_archive import PROFILE as LIFECYCLE_PROFILE
from folioview_shared.identity import owner_key

from ..resources import ResourceUnavailable
from .authority_cutover import UserAuthorityCutover
from .recovery import COLLECTION as HEADS
from .recovery import CurrentHead

PROFILE = "folioview.owner-user-archive-lifecycle.v1"


class PrivateArchiveLifecycle:
    def __init__(self, store, *, clock=time.time):
        self.cutover = UserAuthorityCutover(store)
        self.clock = clock

    def read(self, uid, vault, nonce, operation):
        self.cutover._named_store()
        owner = owner_key(uid)
        try:
            raw = self.cutover._read(((HEADS, owner),))[0]
            if raw is None:
                raise ContractError("not_found")
            head = CurrentHead.model_validate(raw)
            if (head.ownerSubject, head.vaultId) != (owner, vault) or head.handover is None:
                raise ContractError("not_found")
            original = self.cutover.verifier.baselines.read(
                owner, vault, head.handover.baselineDigest
            )
            if original is None:
                raise ContractError("authorization_unavailable")
            original = strict_json_loads(original)
            _, state, bundles = self.cutover.verifier.original_history(original, int(self.clock()))
            if (original["ownerSubject"], original["vaultId"], original["rootKeyId"]) != (
                owner,
                vault,
                head.rootKeyId,
            ) or head.archive.model_dump() != original["archiveBoundary"]:
                raise ContractError("authorization_unavailable")
            if self.cutover._read(((HEADS, owner),))[0] != raw:
                raise ContractError("version_conflict")
            historical = original["archiveLifecycle"]
            history = historical["history"] if historical is not None else []
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
                        "archive": original["archive"],
                        "pendingAuthorization": None,
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
