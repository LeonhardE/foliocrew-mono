# Portfolio metadata reuses exact verified public history

Date: 2026-11-16

## Summary

Metadata reads can reuse a private, bounded proof of a complete signed public registry history
across requests in the same process without retaining a service or store object. Its key binds the complete Root bytes, owner, vault, Root ID and complete history
digest. Each request and conflict retry still reads current rows and validates Root, source state,
epoch/version, time, head and lifecycle; installation and write paths retain full verification.

The memo accepts only successful original verification, returns detached registry wrappers and
has bounded entry/logical-byte LRU retention, with no permission TTL. Misses and capacity do not reject legal requests.
No wire, database budget, deployment capacity or billing configuration changes are included.
Synthetic SDK/SQLite, mutation, time, revocation, retry and concurrency controls cover the boundary;
local measurements do not establish a production two-second result.

## Validation

- Metadata focused controls: 27 passed, including four actual ASGI HTTP requests constructing
  four different service objects; SDK/SQLite responses and fresh zero-write reads match.
- Original authority retry controls: 11 passed; write/install time boundaries remain unchanged.
- Offline paired measurements distinguish first misses, warm hits and expiry; realistic eight-entry
  tracemalloc checks logical accounting separately from retained/transient Python allocations.
- No cloud, private data, provider or browser requests were made.
