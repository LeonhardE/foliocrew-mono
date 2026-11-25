# Opt-in watchlist revision

Date: 2026-11-24

## Summary

Watchlist clients can request the authoritative revision alongside the items they read or save.
Task clients can use the revision to prepare an approved copy of exactly that saved list.

## Changes

- Add `includeRevision=true` to watchlist reads, adds, and deletes. Standard v1 responses retain their existing fields.
- Return the revision from the same SQLite or Firestore transaction as the list. Legacy lists remain uninitialized until an actual change or explicit initialization, and no-op saves retain the current revision.

## Validation

- User Service suite passed all 170 tests, including private API compatibility, legacy and empty lists, no-op mutations, SQLite concurrency, and Firestore transaction retries.
