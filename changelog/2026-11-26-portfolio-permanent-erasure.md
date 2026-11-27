# Permanently erase holdings sources and frozen accounts

Date: 2026-11-26

## Summary

Once the upstream authority acknowledges a signed holdings-source deletion, Portfolio removes
its stored snapshots, operation history, source-specific cancellation receipts, authority replica
and lifecycle state. Source disconnection still preserves the owner's history.

## Changes

- Resume interrupted erasure in bounded transactions and preserve other sources in shared ledgers.
- Reject authority fetches that crossed a deletion before they can reinstall a stale replica.
- Add operator inventory and cleanup commands for old acknowledged deletions and disabled accounts.
  Account verification scans all Portfolio data collections, including unlisted sources.
- Document client recovery for a lost acknowledgement, upstream rollout requirements and the
  separate scope of backup and historical-version verification.

## Validation

- Ran the Portfolio service test suite and lint checks.
- Verified signed deletion, interruption recovery, grant synchronization races, isolation and
  physical readback with SQLite and the Firestore emulator.
