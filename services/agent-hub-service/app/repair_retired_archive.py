"""Inventory or remove one owner's archived copy after a confirmed transfer and deletion."""

import argparse
import json
import os
import sys

from folioview_shared.encrypted.jsonutil import strict_json_loads

from .retired_archive import cleanup_retired_archive
from .store import FirestoreHubStore
from .vaults import VaultService


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--database", choices=["agent-hub"], required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if (
        os.getenv("FIREBASE_PROJECT_ID") != args.project
        or os.getenv("FIRESTORE_DATABASE") != args.database
        or os.getenv("FIRESTORE_EMULATOR_HOST")
    ):
        parser.error("Select the exact Hub runtime project and named database")
    try:
        value = strict_json_loads(sys.stdin.buffer.read(4097), max_bytes=4096)
        if (
            type(value) is not dict
            or value.keys() != {"uid", "vaultId"}
            or type(value["uid"]) is not str
            or not 1 <= len(value["uid"]) <= 128
        ):
            raise ValueError
        service = VaultService(FirestoreHubStore(args.project, args.database))
        result = cleanup_retired_archive(service, value["uid"], value["vaultId"], apply=args.apply)
        if args.apply:
            result = cleanup_retired_archive(service, value["uid"], value["vaultId"], apply=False)
    except Exception:
        parser.exit(
            1,
            "Cleanup unconfirmed. Check the transfer, User receipt, workload identity and retry.\n",
        )
    print(json.dumps({"scope": "hub.retired_archive", "remaining": result["remaining"]}))
    return int(args.apply and result["remaining"] != 0)


if __name__ == "__main__":
    raise SystemExit(main())
