"""Mirror one transferred owner's verified historical terminal source receipts into Hub."""

import argparse
import json
import os
import sys
import time

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from folioview_shared.encrypted.crypto import _signed_parts, signing_input_fingerprint
from folioview_shared.encrypted.jsonutil import strict_json_loads
from folioview_shared.encrypted.private_resources import verify_private_registry_transition

from .account_writes import valid_uid
from .fences import FenceService, _fingerprint, _mutation, _saved_ack
from .source_erasure import erase_source
from .store import FirestoreHubStore, StoreUnavailable, private_resource_writer_fence_path

RECEIPTS = "user_private_source_invalidation_receipts"


def verified_writer(owner, writer, read, now):
    """Bind both databases to the original Root-signed transfer of this vault."""
    if (
        not isinstance(writer, dict)
        or writer.get("state") != "transferred"
        or writer.get("writerEpoch") != 2
    ):
        raise StoreUnavailable
    vault, root = writer["vaultId"], writer["rootKeyId"]
    head = strict_json_loads(read("user_private_recovery_heads", owner)["view"])
    transfer = strict_json_loads(read("user_private_handover_receipts", owner)["record"])
    receipt, signed = transfer["receipt"], transfer["signedTransition"]
    scope = (owner, vault, root)
    if any(
        tuple(row[k] for k in ("ownerSubject", "vaultId", "rootKeyId")) != scope
        for row in (writer, head, receipt)
    ):
        raise StoreUnavailable
    if (
        head["handover"]
        != {k: receipt[k] for k in ("operationId", "writerEpoch", "baselineDigest")}
        or receipt["writerEpoch"] != 2
        or head["vaultVersion"] < receipt["nextVaultVersion"]
        or signing_input_fingerprint(signed) != receipt["transitionFingerprint"]
        or writer["transitionFingerprint"] != receipt["transitionFingerprint"]
    ):
        raise StoreUnavailable
    start = receipt["registryStart"]
    key = _fingerprint([owner, vault, start["registryEpoch"], start["registrySequence"]])
    item = strict_json_loads(read("user_private_registry_history", key)["entry"])
    cursor = verify_private_registry_transition(
        signed,
        first_bundle=item["bundle"],
        root_jwk=item["rootJwk"],
        pinned_root_key_id=root,
        owner_subject=owner,
        vault_id=vault,
        authenticated_start=start,
        now=now,
    )
    transition = _signed_parts(signed)[1]
    if (
        item["head"] != start
        or cursor.head() != start
        or transition["operationId"] != receipt["operationId"]
        or receipt["nextVaultVersion"] != transition["nextVaultVersion"]
    ):
        raise StoreUnavailable


def verified_deletion(owner, vault, key, row, read):
    if set(row) != {"ownerSubject", "vaultId", "request", "fingerprint", "ack"}:
        raise StoreUnavailable
    request = row["request"]
    _mutation(request)
    ref = request["ref"]
    if (
        row["ownerSubject"] != owner
        or request["ownerSubject"] != owner
        or row["vaultId"] != vault
        or ref["sourceService"] != "portfolio"
        or ref["kind"] != "holdings"
        or key != _fingerprint([owner, "portfolio", request["mutationId"]])
    ):
        raise StoreUnavailable
    _saved_ack({k: row[k] for k in ("request", "ack", "fingerprint")}, request)
    if request["reason"] != "deleted":
        return None
    key = _fingerprint([owner, vault, ref["resourceId"]])
    fence = read("user_private_holdings_fences", key)
    if (
        fence
        != {
            "ownerSubject": owner,
            "vaultId": vault,
            "binding": {"ref": ref, "sourceEpoch": request["newSourceEpoch"]},
            "state": "deleted",
            "currentRevision": 0,
        }
        or type(fence["binding"]["sourceEpoch"]) is not int
        or type(fence["currentRevision"]) is not int
    ):
        raise StoreUnavailable
    return request


def repair(store, owner, read, receipts, *, apply=False, clock=time.time):
    marker = store.transact(lambda unit: unit.get(private_resource_writer_fence_path(owner)))
    verified_writer(owner, marker, read, int(clock()))
    counts = {"matched": 0, "completed": 0, "reviewRequired": 0}
    for key, row in receipts:
        try:
            request = verified_deletion(owner, marker["vaultId"], key, row, read)
            if request is not None:
                counts["matched"] += 1
                if apply:
                    FenceService(store, clock=clock).invalidate(
                        request, source_service="portfolio", expected_writer=marker
                    )
                    if erase_source(store, owner, request["ref"]):
                        counts["completed"] += 1
                    else:
                        counts["reviewRequired"] += 1
        except (ValueError, KeyError, StoreUnavailable, TypeError):
            counts["reviewRequired"] += 1
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--database", required=True, choices=["agent-hub"])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if (
        args.project != os.getenv("FIREBASE_PROJECT_ID")
        or os.getenv("FIRESTORE_DATABASE") != args.database
    ):
        parser.error("Select the configured Hub project and named database.")
    if os.getenv("FIRESTORE_EMULATOR_HOST") and not (
        args.project.startswith("demo-")
        and os.environ["FIRESTORE_EMULATOR_HOST"].startswith("127.0.0.1:")
    ):
        parser.error("Use a loopback emulator with a demo project.")
    try:
        owner = valid_uid(sys.stdin.read(130).removesuffix("\n"))
        hub = FirestoreHubStore(args.project, args.database)
        user = firestore.Client(project=args.project, database="user-data")

        def read(table, key):
            return user.collection(table).document(key).get().to_dict()

        entries = (
            user.collection(RECEIPTS)
            .where(filter=FieldFilter("ownerSubject", "==", owner))
            .stream()
        )
        counts = repair(hub, owner, read, ((r.id, r.to_dict()) for r in entries), apply=args.apply)
    except Exception:
        parser.exit(
            1, "Repair unconfirmed. Check the source receipt, transfer and service identities.\n"
        )
    print(json.dumps({"scope": "hub.retired_sources", **counts}, sort_keys=True))
    return int(bool(counts["reviewRequired"]))


if __name__ == "__main__":
    raise SystemExit(main())
