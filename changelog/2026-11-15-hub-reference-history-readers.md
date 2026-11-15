# Prepare Hub readers for lossless registry history references

Date: 2026-11-15

## Summary

Add the Hub reader floor for the shared lossless internal history representation before any
writer activation. Existing writes and public wire DTOs retain their current behavior.

## Changes

- Decode legacy and reference history for Vaults and frozen persistent Runs through the same
  SQLite single/batch/retention and Firestore reader boundary, without read migrations.
- Bound physical stored rows and expanded histories independently, preserve private snapshots
  and original JWS bytes, and retain all original authority checks and cache isolation.
- Document the required reader-first deployment and rollback floor. Reference writer activation
  remains a separate release; the 768 KiB write and public HTTP/response budgets stay unchanged.

## Validation

- Real SQLite and Firestore SDK synthetic RPC regressions cover original responses, 24-bundle
  histories, all read paths, malformed/native numeric references, budgets, authority failures,
  independent snapshots, tombstones, unchanged legacy writes and atomic large-write rejection.
- Full repository checks are required before commit.
