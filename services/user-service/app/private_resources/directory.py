"""Read the private resource index and Owner list metadata without a self-request."""

from pydantic import ValidationError

from folioview_shared.encrypted.budgets import check_read_response
from folioview_shared.encrypted.constants import CONTRACT_VERSION
from folioview_shared.encrypted.errors import ContractError
from folioview_shared.encrypted.private_resources import source_index_digest
from folioview_shared.identity import owner_key

from ..resources import ResourceUnavailable, read_list_catalogue
from .authority_cutover import UserAuthorityCutover
from .recovery import COLLECTION as HEADS
from .recovery import CurrentHead
from .report_sources import HOLDINGS_FENCES, HoldingsFence, holdings_fence_key
from .source_invalidations import SOURCE_INDEX

DIRECTORY_PROFILE = "folioview.owner-private-resource-directory.v1"
_STATES = {"active": "eligible", "revoking": "revoking", "disconnected": "disconnected"}


class PrivateResourceDirectory:
    def __init__(self, store):
        self.store = store
        self.cutover = UserAuthorityCutover(store)

    def read(self, uid, vault, nonce):
        self.cutover._named_store()
        owner = owner_key(uid)

        def snapshot(read, _write):
            raw, index = read(((HEADS, owner), (SOURCE_INDEX, owner)))
            if raw is None:
                raise ContractError("not_found")
            head = CurrentHead.model_validate(raw)
            if (head.ownerSubject, head.vaultId) != (owner, vault) or head.handover is None:
                raise ContractError("not_found")
            if (
                type(index) is not dict
                or index.keys() != {"ownerSubject", "vaultId", "entries"}
                or (index["ownerSubject"], index["vaultId"]) != (owner, vault)
                or source_index_digest(index["entries"]) != head.sourcesDigest
            ):
                raise ContractError("source_unavailable")
            holdings = [
                item for item in index["entries"] if item["binding"]["ref"]["kind"] == "holdings"
            ]
            paths = tuple(
                (
                    HOLDINGS_FENCES,
                    holdings_fence_key(owner, vault, item["binding"]["ref"]["resourceId"]),
                )
                for item in holdings
            )
            output = []
            for entry, raw in zip(holdings, read(paths) if paths else (), strict=True):
                fence = HoldingsFence.model_validate(raw).model_dump()
                if (
                    (fence["ownerSubject"], fence["vaultId"]) != (owner, vault)
                    or fence["binding"] != entry["binding"]
                    or fence["state"] != _STATES[entry["state"]]
                ):
                    raise ContractError("source_unavailable")
                output.append(
                    {
                        **entry["binding"],
                        "state": entry["state"],
                        "revision": fence["currentRevision"],
                    }
                )
            return head, output

        try:
            head, holdings = self.cutover._transaction(snapshot, writes=False)
            lists = read_list_catalogue(self.store, uid, ("watchlist", "channel_follows"))
            result = {
                "contractVersion": CONTRACT_VERSION,
                "profile": DIRECTORY_PROFILE,
                "ownerSubject": owner,
                "vaultId": vault,
                "nonce": nonce,
                "registry": head.registry.model_dump(),
                "sourcesDigest": head.sourcesDigest,
                "holdings": holdings,
                "lists": lists["items"],
                "readAt": lists["readAt"],
            }
            check_read_response(result)
            return result
        except ContractError:
            raise
        except ResourceUnavailable as error:
            if isinstance(error.__cause__, ContractError):
                raise error.__cause__ from None
        except (ValidationError, KeyError, TypeError, ValueError):
            pass
        raise ContractError("source_unavailable")
