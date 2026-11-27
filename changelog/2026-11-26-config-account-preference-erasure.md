# Erase stored preferences for a verified account

Date: 2026-11-26

## Summary

Config operators can inspect and remove the three preference records for one account.

## Changes

- Remove legacy UI, language, and currency records together. Verify every document after a Firestore delete.
- Keep owner data out of output and check that the Firebase identity is disabled before cloud deletion.

## Validation

- Two-owner SQLite regression tests cover malformed legacy data and repeated erasure. Firestore adapter tests cover atomic writes and incomplete readback.
