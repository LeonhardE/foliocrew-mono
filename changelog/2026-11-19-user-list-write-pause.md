# Preserve list reads during User database handoff

Date: 2026-11-19

## Summary

Support the short read-only phase for the INF-023 User database migration.

## Changes

- Add an opt-in pause for actual watchlist, currency follow, channel follow and initialization writes.
- Preserve current reads, no-op changes and replay of recorded initialization receipts.

## Validation

- Local database tests cover reads, blocked writes, original receipt replay and resumed writes.
