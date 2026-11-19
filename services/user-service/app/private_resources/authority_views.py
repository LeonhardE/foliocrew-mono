"""Read current User authority by exact owner, epoch and consumer scope."""

from pydantic import ValidationError

from folioview_shared.encrypted.budgets import check_read_response
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.jsonutil import canonical_json, strict_json_loads
from folioview_shared.encrypted.legacy_archive import validate_passkey_archive
from folioview_shared.encrypted.private_resources import (
    PRIVATE_AUTHORITY_PROFILE,
    private_authority_lookup,
    source_index_digest,
)
from folioview_shared.identity import owner_key

from ..resources import ResourceUnavailable
from .authority_cutover import UserAuthorityCutover
from .legacy_baselines import _sha
from .recovery import COLLECTION as HEADS
from .report_sources import HOLDINGS_FENCES, HoldingsFence, holdings_fence_key
from .source_invalidations import SOURCE_INDEX
from .source_registrations import _matches_current, current_registry

OWNER_CURRENT_PROFILE = "folioview.owner-current-user-vault.v1"


def _recipient_keys(registry, now):
    writers, recipients, kinds = [], [], set()
    for key in sorted(registry.active_key_ids):
        try:
            certificate = registry.cert(key, connection_id=None, now=now)
        except ContractError as error:
            if error.code != "key_authorization_required":
                raise
            continue
        role = certificate["role"]
        if role == "device_sig" and "object_write" in certificate["capabilities"]:
            writers.append(key)
        if role in ("device_enc", "recovery_enc"):
            recipients.append(key)
            kinds.add(role)
    if (
        not 1 <= len(writers) <= 8
        or not 2 <= len(recipients) <= 8
        or kinds != {"device_enc", "recovery_enc"}
    ):
        raise ContractError("key_authorization_required")
    return writers, recipients


class PrivateAuthorityViews:
    def __init__(self, store):
        self.cutover = UserAuthorityCutover(store)

    def owner_current(self, uid, nonce, *, now):
        """Read the original sealed archive together with only current authority."""
        self.cutover._named_store()
        owner = owner_key(uid)
        head = self.cutover._read(((HEADS, owner),))[0]
        if head is None or head.get("handover") is None:
            raise ContractError("not_found")
        vault_id = head["vaultId"]
        lookup = self.lookup(
            uid,
            {
                "contractVersion": CONTRACT_VERSION,
                "profile": PRIVATE_AUTHORITY_PROFILE,
                "consumer": "hub",
                "ownerSubject": owner,
                "vaultId": vault_id,
                "sourceId": None,
                "minimumRegistryEpoch": head["registryStart"]["registryEpoch"],
                "nonce": nonce,
            },
            now=now,
        )["authority"]
        baseline = self.cutover.verifier.baselines.read(
            owner, vault_id, head["handover"]["baselineDigest"]
        )
        if baseline is None:
            raise ContractError("source_unavailable")
        original = strict_json_loads(baseline)
        archive = original["archive"]
        root = lookup["rootKeyId"]
        validate_passkey_archive(archive, owner=owner, vault=vault_id, root=root)
        if lookup["archive"] != original["archiveBoundary"] or lookup["archive"]["digest"] != _sha(
            canonical_json(archive)
        ):
            raise ContractError("source_unavailable")
        result = {
            "contractVersion": CONTRACT_VERSION,
            "profile": OWNER_CURRENT_PROFILE,
            "ownerSubject": owner,
            "nonce": nonce,
            "vault": {
                "vaultId": vault_id,
                "rootKeyId": root,
                "rootJwk": lookup["rootJwk"],
                "version": lookup["vaultVersion"],
                "archive": archive,
                "registryHistory": lookup["registryHistory"],
            },
            "proof": {
                key: lookup[key]
                for key in (
                    "registry",
                    "registryStart",
                    "signedTransition",
                    "archive",
                    "sourcesDigest",
                    "sources",
                )
            },
        }
        check_read_response(result)
        return result

    def lookup(self, uid, request, *, now):
        checked = private_authority_lookup(request)
        owner, vault, source = owner_key(uid), checked["vaultId"], checked["sourceId"]
        if owner != checked["ownerSubject"]:
            raise ContractError("insufficient_scope")
        try:
            evidence, registry, bundles = current_registry(self.cutover, uid, vault, now)
            head = evidence["registry"]
            if head["registryEpoch"] < checked["minimumRegistryEpoch"]:
                raise ContractError("rollback_detected")
            cells = ((HEADS, owner), (SOURCE_INDEX, owner))
            if source is not None:
                cells += ((HOLDINGS_FENCES, holdings_fence_key(owner, vault, source)),)

            def snapshot(read, _create):
                current, source_index, *rows = read(cells)
                if (
                    not _matches_current(current, evidence)
                    or current["sourcesDigest"] != evidence["sourcesDigest"]
                    or type(source_index) is not dict
                    or source_index.keys() != {"ownerSubject", "vaultId", "entries"}
                    or (source_index["ownerSubject"], source_index["vaultId"]) != (owner, vault)
                    or source_index_digest(source_index["entries"]) != current["sourcesDigest"]
                ):
                    raise ContractError("version_conflict")
                entries = source_index["entries"]
                if source is None:
                    return {"sources": entries}
                if rows[0] is None:
                    raise ContractError("not_found")
                fence = HoldingsFence.model_validate(rows[0]).model_dump()
                binding = fence["binding"]
                if (
                    (fence["ownerSubject"], fence["vaultId"]) != (owner, vault)
                    or binding["ref"]["resourceId"] != source
                    or fence["state"] != "eligible"
                    or {"binding": binding, "state": "active"} not in entries
                ):
                    raise ContractError("source_unavailable")
                writers, recipients = _recipient_keys(registry, now)
                return {
                    "sourceId": source,
                    "resourceRef": binding["ref"],
                    "sourceEpoch": binding["sourceEpoch"],
                    "writerKeyIds": writers,
                    "recipientKeyIds": recipients,
                }

            selected = self.cutover._transaction(snapshot, writes=False)
            result = {
                "contractVersion": CONTRACT_VERSION,
                "profile": checked["profile"],
                "consumer": checked["consumer"],
                "nonce": checked["nonce"],
                "requestDigest": _sha(canonical_json(checked)),
                "authority": {
                    **{
                        key: evidence[key]
                        for key in (
                            "ownerSubject",
                            "vaultId",
                            "rootKeyId",
                            "rootJwk",
                            "vaultVersion",
                            "registry",
                            "registryStart",
                            "archive",
                            "signedTransition",
                            "sourcesDigest",
                        )
                    },
                    "registryHistory": bundles,
                    **selected,
                },
            }
            check_read_response(result)
            return result
        except ContractError:
            raise
        except ResourceUnavailable as error:
            if isinstance(error.__cause__, ContractError):
                raise error.__cause__ from None
            raise ContractError("source_unavailable") from None
        except (ValidationError, TypeError, ValueError, KeyError):
            raise ContractError("source_unavailable") from None
