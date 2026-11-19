# Reuse User list metadata in-process

Date: 2026-11-19

## Summary

User exposes its current list metadata to authorized code in the same deployment and reuses it from the existing delegated routes.

## Changes

- Read watchlist and channel metadata from one validated snapshot, with exact Owner and incarnation checks for binding reads.
- Preserve existing responses, source metadata, initialization receipts, and no-write read behavior during migration.

## Validation

- User tests cover direct and delegated metadata reads, original initialization and replay, and cross-account and wrong-incarnation requests.
