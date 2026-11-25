# Preserve pending watchlist updates from locked Market

Date: 2026-11-24

## Summary

Watchlist edits saved on Market can resume Agent synchronization after reloading the page and
unlocking the same vault on a browser with a verified local vault record.

## Changes

- Keep the server-confirmed watchlist revision in local storage under the signed-in owner's pinned
  vault. Market can record it while the vault is locked using its existing watchlist request.
- Move the revision into the existing retry queue in a single transaction after unlock. Check the
  current source and grants before sending an Agent update.
- Keep same-tab retries when the browser cannot persist the revision. A known vault must match
  the vault that eventually unlocks.

## Validation

- Focused coverage exercises reload and unlock, account and vault mismatches, a deleted archive,
  a canceled owner session, and concurrent revision updates.
- The repository check covers Web types, tests, formatting, and shared contract checks.
