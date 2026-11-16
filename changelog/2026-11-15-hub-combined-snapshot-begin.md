# Combine the first resource snapshot read with transaction start

Date: 2026-11-15

## Summary

Remove a separate database transaction-start round trip from the catalogue's initial
snapshot and resource display's final snapshot while retaining their real commits and
complete current authorization checks.

## Changes

- Opt these two read callbacks into Firestore's explicitly read-write `new_transaction`
  BatchGet option. Keep ordinary write transactions and SQLite transaction behavior.
- Accept the official ID-only and ID-with-document first frames, reject incomplete,
  duplicate or foreign responses, and preserve bounded rollback and commit-only
  conflict retries. Callback views reject writes and own fresh rows per attempt.
- Preserve all Root/history, current-time, source and final-fence checks, the existing
  request-local static verification memo, byte budgets and cloud resource settings.

## Validation

- Real Firestore SDK streams cover lifecycle, malformed/partial responses, cancellation,
  known/unknown transaction IDs, retries, supplemental reads and zero-write commits.
- Valid signed 24- and 25-generation storage-reference histories produce the same DTOs
  as the original transaction path and SQLite. Two warm snapshots use four RPCs rather
  than six. This local regression does not establish a production latency result.
