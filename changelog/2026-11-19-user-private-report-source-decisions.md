# Evaluate report sources against current User data

Date: 2026-11-19

## Summary

Add the opt-in User decision endpoint for exact, authenticated Hub report attempts.

## Changes

- Evaluate the current vault, in-process list metadata and exact holdings fences in one bounded User transaction.
- Refuse stale or revoked inputs, fail on unreadable authority, and bind each decision to its originating report attempt.

## Validation

- SQLite and mocked Firestore tests cover one-snapshot reads, both revocation orderings, replacement, scope, and missing credentials.
