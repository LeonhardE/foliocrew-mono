# Hub explicit large-history reader floor

Date: 2026-11-15

## Summary

Prepare Hub storage readers for explicitly versioned larger histories without activating
larger writes or changing public responses.

## Changes

- Decode storage.v2 only for Vault and frozen persistent Run rows, with separate history,
  non-history and whole-row bounds while retaining the 768 KiB physical ceiling.
- Preserve legacy/storage.v1 limits, native numeric types, private snapshots, authority checks
  and expanded cache accounting across SQLite and Firestore single, batch and retention reads.
- Keep current writers on storage.v1 and existing wire limits; document downstream reader
  prerequisites before any expanded writer rollout.

## Validation

- Focused SQLite and real Firestore SDK boundary regressions cover larger Root-signed histories,
  old-format budgets, malformed references, numeric types, cache isolation and unchanged writers.
