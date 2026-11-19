# Read the transferred private resource directory from User

Date: 2026-11-19

## Summary

Read the same-account private source index and current list metadata from
the User service.

## Changes

- Verify current source fences against the scoped User index.
- Read watchlist and channel metadata in-process alongside the private
  source projection.
- Require the verified Owner and trusted Web work identity.

## Validation

- Verify retired holdings remain absent and uninitialized lists keep their
  ordinary metadata contract.
- Run repository-wide checks.
