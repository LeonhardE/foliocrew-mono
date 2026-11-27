# Erase User service account data and retired names

Date: 2026-11-26

## Summary

Verified account deletion now has an operator path that physically removes User service data and rereads the database to establish the outcome. A deleted holdings source no longer leaves its encrypted name or rename history accessible.

## Changes

- Inventory current and legacy stores, including packed owner history, account lists and versions, invitations, memberships and FX preferences.
- Verify the suspended Firebase and Google identity, use conditional deletes, support retries and independently verify the remaining record count.
- Remove historical migrated key envelopes on verified archive deletion. Verify the signed registry and lifecycle without the original sealed keys, reject restaging, and expose the original removal evidence only to an authorized Hub caller.
- Support read-only restore checks after identity deletion and private capture of invitation delivery references.
- Remove a retired holdings source's aliases before acknowledging Portfolio. Support catch-up for existing deletions.
- Accept Hub baselines with a cumulative retired source count while keeping existing digests and current source ownership checks intact.
- Allow invitation administrators to permanently remove revoked or expired invitations after checking the exact revision.

## Validation

- Ran the full User service suite with the loopback Firestore emulator enabled. The tests cover interrupted batches, repeated deletion, invitation revisions, source incarnation isolation, historical wrapped keys, trusted Hub receipt lookup and other accounts.
- Restored a pre-removal SQLite copy in isolation and reapplied the same account scope through physical deletion to zero remaining records.
- Verified the repository checks with `npm run check`.
