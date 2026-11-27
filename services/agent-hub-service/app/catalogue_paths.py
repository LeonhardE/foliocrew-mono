"""Store-local bounded path hints, never source data or authorization evidence."""

import re
import threading
import time
from collections import OrderedDict

_FENCE_PATH = re.compile(r"hub_source_fences/[0-9a-f]{64}\Z")
_MAX_OWNERS = 64
_MAX_KEYS = 10
_TTL_SECONDS = 300


class FenceKeyHints:
    """Only successfully read directories publish immutable document-key tuples.

    Each Store owns its own instance. A hit merely chooses which documents to
    read freshly; consumers must derive and verify the real paths again from
    the current verified Vault in that same transaction attempt.
    """

    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._entries = OrderedDict()

    def get(self, owner):
        with self._lock:
            entry = self._entries.pop(owner, None)
            if entry is None:
                return None
            expires, paths = entry
            if self._clock() >= expires:
                return None
            self._entries[owner] = entry
            return paths

    def remember(self, owner, paths):
        # This is an internal optimization. An unsupported value must not turn
        # a successful authoritative read into an error or enter the cache.
        if (
            type(paths) is not tuple
            or len(paths) > _MAX_KEYS
            or any(
                not isinstance(path, str) or _FENCE_PATH.fullmatch(path) is None for path in paths
            )
            or len(set(paths)) != len(paths)
        ):
            return
        with self._lock:
            self._entries.pop(owner, None)
            self._entries[owner] = (self._clock() + _TTL_SECONDS, paths)
            while len(self._entries) > _MAX_OWNERS:
                self._entries.popitem(last=False)

    def discard(self, owner):
        with self._lock:
            self._entries.pop(owner, None)
