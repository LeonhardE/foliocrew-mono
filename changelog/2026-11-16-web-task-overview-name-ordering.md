# Use task overview packets before reading task names again

Date: 2026-11-16

## Summary

Returning to the Tasks page after a hidden document no longer starts a redundant task-packet request
from retained list rows while the current overview is still loading.

## Changes

- Coordinate automatic name backfill with the current successful metadata-read receipt and adopt
  validated inline packets with that same list before requesting missing packets.
- Fence late name successes and failures to their original receipt. Preserve the displayed list,
  explicit retries, partial/large packet fallback, original freshness timestamps and the two-worker
  verification bound.
- Keep task names behind the existing Owner Worker verifier and preserve real unread counts,
  report provider attribution, scope changes and visibility cancellation.

## Validation

- The real three-hook visibility regression fails on the previous source and passes with this
  change: three covered names use one overview without a duplicate packet query.
- Targeted regressions cover more than four tasks, null/partial inline packets, shrinking short
  pages, metadata failure and explicit retry, legacy mode, stale receipt success/error, scope
  changes, unread/provider completeness and original Worker concurrency controls.
- All 79 targeted controller/overview/boundary tests, Web type checking and changed-file formatting
  pass. The 13 Owner Worker hash inputs remain byte-identical to the base revision.
