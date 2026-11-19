# Serve current private authority to Hub and Portfolio

Date: 2026-11-19

## Summary

Serve the transferred account's current signed User registry through bounded,
separately authenticated Hub and Portfolio lookups.

## Changes

- Rebuild the current registry from its verified signed epoch start and
  bind the response to the original request.
- Return only the current scoped source projection to Portfolio.
- Recheck the live authority and source index inside the read transaction.
- Keep both readers disabled until deployment is explicitly opted in.

## Validation

- Verify epoch and owner checks, distinct authenticated paths, and rejection
  of a source after invalidation.
- Run the repository-wide checks.
