# Keep a missing market chart local to its series

Date: 2026-11-19

## Summary

An instrument with no Yahoo price history can no longer pause refreshes for unrelated
instruments. A stored chart for that same series stays available with its freshness warning.

## Changes

- Keep missing and unusable history on the affected shared cache key and release its refresh lease.
- Report no available prices for a cold missing series. Leave shared provider protection in place
  for confirmed rate limiting and upstream errors.

## Validation

- Verify cold missing history, a successful unrelated refresh, per-key retry suppression and explicit
  provider rate limiting in the Market suite.
- Verify the Firestore failure path updates only the affected cache key.
