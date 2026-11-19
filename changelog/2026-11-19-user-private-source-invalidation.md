# Commit private source invalidations in User

Date: 2026-11-19

## Summary

Add a gated internal endpoint for Portfolio source invalidation. The current
User writer is required before an invalidation can change source authority.

## Changes

- Require the dedicated Portfolio workload and the fixed User audience.
- Advance the current incarnation's fence, recovery digest, and original
  operation receipt in one transaction. Preserve exact replay and terminal
  deletion across retries.
- Keep the endpoint disabled until the migration installs the User writer
  and the matching source index.

## Validation

- Verify report authorization, source incarnation isolation, exact replay,
  route authentication and rollback after a failed receipt write.
- Run the repository-wide checks.
