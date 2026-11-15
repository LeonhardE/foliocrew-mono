# Recheck first-enrollment authority on transaction retries

Date: 2026-11-15

## Summary

New vault enrollment now checks the complete initial registry and current selected keys
at each database transaction attempt's time, so an aborted transaction cannot commit a
new vault after the required Owner certificates expire.

## Changes

- Reuse the original complete vault-row and writer/recipient validators before staging
  a genuinely new vault or bootstrap operation record.
- Preserve exact committed bootstrap replay behavior, immutable root/archive binding,
  current registry/source projection and existing request/response budgets.
- Add real Firestore SDK retry and SQLite transaction-wait regressions using synthetic
  keys and an in-memory RPC boundary.

## Validation

- Targeted first-enrollment expiry, clock rollback, successful retry, current-state
  replay, competing-root and atomicity regressions.
