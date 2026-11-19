# Support a cache-only Market migration window

Date: 2026-11-19

## Summary

Market can serve existing cache entries during the last database copy without reserving or refreshing upstream data.

## Changes

- Add an explicit cache-only mode that preserves reads and fences shared writes at the cache boundary.
- Keep both provider budgets and cache data intact until the new database becomes the sole writer.

## Validation

- The Market tests cover a stale but readable chart and disabled upstream and shared writes in cache-only mode.
