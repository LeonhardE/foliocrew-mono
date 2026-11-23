# Refresh market snapshots on demand

Date: 2026-11-23

## Summary

Signed-in workspace members can refresh the index overview and selected chart even when
automatic market requests have used the shared allowance.

## Changes

- Add a closed, authenticated refresh command for public overview and chart data.
- Share existing cached data, short duplicate-request protection, and real Yahoo throttling
  across both market pages.

## Validation

- Verify anonymous requests are rejected, and a full automatic allowance does not prevent the
  signed-in refresh from updating both daily quotes and a selected chart range.
- Run `npm run check`.
