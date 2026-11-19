# Verify current User authority in Portfolio

Date: 2026-11-19

## Summary

Allow the selected transferred account to fetch the exact holdings authority
from User and verify the same-Root signed start before replacing its replica.

## Changes

- Bind the fixed User lookup to the account, vault, source and fresh nonce.
- Verify the new registry start and continuing signatures on installation
  and later reads. Reject attempts to restore the old epoch.
- Store transferred registry history in bounded segments using the existing
  reference encoding. Legacy rows keep their existing representation.

## Validation

- Exercise the scoped transport, a 33-checkpoint transferred replica,
  current snapshot write and old format rollback refusal.
- Run the repository-wide checks.
