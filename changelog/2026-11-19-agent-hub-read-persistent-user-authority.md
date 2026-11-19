# Persistent Agent views verify the current User authority

Date: 2026-11-19

## Summary

Read persistent identity, resource consent, and task publication state from a transferred workspace without reading the retired Hub vault.

## Changes

- Check the current User proof against the Hub transfer marker within the read transaction. A current Agent connection must carry the exact transition fingerprint.
- Resolve exact historical operation receipts through the original connection index when User is temporarily unavailable.

## Validation

- Exercise the transferred state, rejection of an old connection, a marker race, and retained receipts in SQLite.
