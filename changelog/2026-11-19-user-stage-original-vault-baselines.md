# Stage an original encrypted vault baseline in User

Date: 2026-11-19

## Summary

The migration can keep the existing encrypted Passkey archive, original lifecycle and source anchors in the User database under a reviewed immutable key.

## Changes

- Verify the existing signed chain and retain its exact head alongside the archive and original receipts. The signed history stays in its dedicated paged storage.
- Scope baseline reads and writes to the original Owner, vault and expected digest.
- Use create-only writes in `user-data`. Repeating the same plan reads back the exact bytes without publishing an active recovery head.

## Validation

- Exercise SQLite, Firestore transaction behavior, exact retries, corruption, and isolation between accounts and vaults.
- Rehearse on a temporary database with the approved production account's preserved archive and original lifecycle.
- Run the repository checks.
