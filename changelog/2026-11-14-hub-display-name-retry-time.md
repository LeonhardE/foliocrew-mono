# Recheck display-name authorization time on transaction retries

Date: 2026-11-14

## Summary

A new encrypted resource-name update could retain its first attempt's authorization
time after a Firestore conflict retry, allowing a certificate or control to expire
before the successful attempt. Use the current server clock inside each attempt.

## Changes

- Sample a strict bounded current clock inside each display-name read/list/write callback.
- Recheck certificate validity, signed-control age and checkpoint time after retries or a
  database wait; preserve static signature reuse and all current source/fence checks.
- Keep exact already-committed operation receipts replayable after signer expiry, with
  their original acceptedAt and no new alias or receipt writes.

## Validation

- All 22 display-name focused tests pass, including seven new real Firestore SDK / SQLite
  regressions for ABORTED retries crossing certificate/control expiry, successful-attempt
  timestamps, original receipt replay and fresh read/list retry clocks.
- SQLite transaction-wait and invalid-clock cases verify fail-closed behavior.
- The mandatory full repository precommit checks and exact PR CI run before release.
