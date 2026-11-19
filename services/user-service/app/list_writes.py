"""Keep list reads and recorded receipts available during database handoff."""

import os


def require_list_writes(unavailable: type[Exception]) -> None:
    if os.getenv("USER_LIST_WRITES_PAUSED") == "true":
        raise unavailable
