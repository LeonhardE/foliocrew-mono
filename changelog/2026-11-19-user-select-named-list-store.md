# Read User lists from the named database

Date: 2026-11-19

## Summary

Switch the read-only User list configuration to the verified INF-023 copy.

## Changes

- Use `user-data` for existing User list and initialization data while writes remain paused.

## Validation

- Review the exact saved database change, then verify current authenticated list reads before resuming writes.
