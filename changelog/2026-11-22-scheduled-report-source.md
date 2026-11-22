# Scheduled source in task report history

Date: 2026-11-22

## Summary

Task history shows a scheduled source when a report belongs to a preparation that matched the authorized schedule.

## Changes

- Match the exact schedule slot and grace window at preparation.
- Recover the display source from the original preparation after rule edits or assignment removal.
- Preserve original Run bindings, report ciphertext, and receipts.

## Validation

- Exercise signed scheduled preparation, result history after cleanup, and original receipt recovery.
- Verify that unrelated schedule-shaped identifiers and mismatched results stay unknown.
