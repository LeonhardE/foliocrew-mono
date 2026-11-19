# Refresh all displayed exchange rates in one request

Date: 2026-11-19

## Summary

The exchange-rate refresh button reloads the displayed rates with one batch Market request.

## Changes

- Keep subscription loading and portfolio currency preferences on their existing loading and retry paths.
- Use the normal shared-cache request directly on explicit refresh. Initial load continues to render
  a cached snapshot while refreshing only when necessary.

## Validation

- Verify that the panel refreshes only rates, and that manual refresh uses one batch request even
  when Market still returns stale data.
