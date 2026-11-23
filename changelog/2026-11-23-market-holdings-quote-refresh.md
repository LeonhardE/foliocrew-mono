# Reuse closing quotes and admit full holdings updates

Date: 2026-11-23

## Summary

Repeated weekend and after-hours requests were consuming the shared daily quota
while receiving the same end-of-session observations. A 22-position update also
required more than the previous shared minute threshold.

## Changes

- Reuse verified latest regular close observations until the next weekday open.
- Let holdings batches use up to 64 weighted units in the shared minute counter.
  Keep the existing daily quota and limit each request to four symbols.
- Expose daily and minute denials on an otherwise valid quote response that can
  contain both newly priced and previously cached rows.

## Validation

- Verify weekend cache reuse, subsequent market-open refresh, six groups covering
  22 positions, and browser-readable quota feedback without losing cached prices.
- Run the full repository check before publication.
