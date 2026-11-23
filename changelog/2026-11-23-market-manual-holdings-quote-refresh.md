# Allow manual holdings quote refresh

Date: 2026-11-23

## Summary

Signed-in workspace members can request the latest holdings quotes when automatic refreshes
have used the shared allowance.

## Changes

- Added a bounded, authenticated path that checks supported quotes without using the
  automatic minute or daily budget.
- Reuse concurrent work and results from the last 30 seconds. Keep previous observations and
  report provider throttling, pending work, and temporary failures.

## Validation

- Exercised signed workspace tokens and rejected anonymous or unadmitted callers.
- Verified the manual path refreshes with a full automatic budget and retains previous prices
  when Yahoo Finance throttles further requests.
- Ran `npm run check`.
