# Avoid repeated resource catalogue reads while reopening a snapshot

Date: 2026-11-14

## Summary

Refreshing saved holdings can briefly clear decrypted content before the same verified snapshot is
published again. Treating both UI changes as a resource change started two catalogue requests,
canceling the first in the browser after it had already reached the backend.

## Changes

- Retain the last published snapshot identity across the temporary content gap.
- Refresh the catalogue when a different verified snapshot is published; keep existing Owner,
  vault and source-epoch scope invalidation and explicit catalogue retry behavior.

## Validation

- Actual component regression covers reopening the same snapshot and publishing a different one.
- `npm run check` is required before commit.
