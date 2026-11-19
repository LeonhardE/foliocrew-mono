# Read account preferences in one request

Date: 2026-11-19

## Summary

Config now offers a unified Owner read for UI, language, and currency preferences.

## Changes

- Batch the three account keys in one Firestore request or SQLite query and retain each setting's independent version.
- Return effective values and distinguish absent or malformed records. The existing reads and version-fenced writes remain available for compatible rollout.

## Validation

- Config tests cover legacy revisions, explicit system appearance and Traditional Chinese, missing and malformed values, scope, no-store headers, and incomplete batches.
