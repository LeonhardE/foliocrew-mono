# Show the outcome of a manual quote update

Date: 2026-11-23

## Summary

A completed manual refresh can legitimately return the same observations. The
holdings page now confirms the result of each completed update.

## Changes

- Report the number of securities with a new price or observation time.
- Confirm when the update returned no newer quotes. Keep the existing detailed
  feedback for throttled and failed requests.

## Validation

- Test unchanged, updated, and failed manual refresh results.
- Run the full repository check before publication.
