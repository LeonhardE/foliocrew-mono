# Retire User runtime access to the shared database

Date: 2026-11-19

## Summary

Retire the legacy User Datastore User membership after the INF-023 write and rollback checks.

## Changes

- Remove the exact conditional User runtime grant on `(default)`.
- Preserve the named `user-data` grant and authentication permissions.

## Validation

- Apply the exact reviewed administrator deletion after verifying cutover writes and their compatible rollback read.
