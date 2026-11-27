"""Inspect or finish Portfolio source deletions already acknowledged by their authority."""

import json
import time

from .erase_account import operator_arguments, operator_target
from .erasure import legacy_sources, purge_source


def main(argv=None):
    parser = operator_arguments(__doc__)
    args = parser.parse_args(argv)
    try:
        store = operator_target(parser, args)
        if args.apply:
            for owner, source in legacy_sources(store):
                purge_source(store, owner, source, now=int(time.time()))
        remaining = sum(1 for _ in legacy_sources(store))
    except Exception:
        parser.exit(1, "Legacy source erasure incomplete. Check the database and retry.\n")
    print(json.dumps({"scope": "portfolio.acknowledged_deletions", "remaining": remaining}))
    return int(args.apply and remaining > 0)


if __name__ == "__main__":
    raise SystemExit(main())
