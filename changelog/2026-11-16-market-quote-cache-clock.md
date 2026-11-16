# Retain quote caches written at fractional-second times

Date: 2026-11-16

## Summary

A valid quote could disappear on the next read because its precise cache expiry
was compared with a whole-second public timestamp. The same entry then prevented
another provider fetch because its original expiry had not passed.

## Changes

- Bind the precise internal update time to the public collection second and use
  that update time for the existing 900-second expiry bound. Existing persisted
  fractional entries work without a migration, rounding or additional TTL.
- Reject invalid, inconsistent and future internal times. A write newer than the
  request's clock remains conservatively unavailable until a later normal read;
  no automatic re-read or retry is added.
- Preserve quote validation, cache writers, leases, provider work and budgets.
  Cloud resources, capacity and billing configuration remain unchanged. Normal
  requests retain their existing usage charges; live recovery needs verification.

## Validation

- Real SQLite and pinned Firestore SDK encoding, transaction and snapshot parsing
  reproduce the original failure and verify persisted reads, local copies,
  invalidation, cache restart and two-instrument merging without extra upstream
  lookups. Only the final Firestore RPC transport is replaced with memory.
- Regressions cover exact expiry and its adjacent floating-point boundaries,
  existing fractional and integer entries, invalid or absent internal times,
  seven-day and future rejection, concurrent writes and provider failure retaining
  a usable old price. The original source fails and the fix passes.
