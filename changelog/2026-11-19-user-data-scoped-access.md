# Scope access to the named User database

Date: 2026-11-19

## Summary

Prepare named database access before the INF-023 User data copy.

## Changes

- Deny direct client access through the named Firebase Rules release.
- Give the existing User runtime a Datastore User grant scoped to `user-data`.

## Validation

- Administrator tests verify the exact condition, runtime identity, deny rules and disabled defaults.
