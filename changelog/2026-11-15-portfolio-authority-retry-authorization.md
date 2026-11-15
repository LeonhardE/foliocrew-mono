# Recheck authority selection on Portfolio transaction retries

Date: 2026-11-15

## Summary

Public authority installation now validates current writer and recipient eligibility at
each transaction attempt's time, so an aborted attempt cannot install an active replica
after its required certificates expire.

## Changes

- Move the existing complete incoming authority and active-key checks into the sync
  transaction, using the same fresh attempt time for previous and candidate rows.
- Take the internal installation adapter's time inside its transaction callback.
- Preserve current Root/history-prefix/source-epoch/lifecycle checks, inactive fencing,
  local CAS, encrypted snapshot validation and original receipt reads.
- Refuse initially invalid sync projections during the first read-only transaction
  attempt, with the original error and no persisted writes.

## Validation

- Actual Firestore SDK retries, synthetic ASGI and SQLite wait regressions cover expiry,
  clock rollback, valid retries, current-state conflicts, inactive fencing and receipts.
