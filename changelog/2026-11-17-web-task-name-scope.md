# Restore task names after workspace unlock

Date: 2026-11-17

## Summary

Task Center can finish loading task names after a signed-in page restores its unlocked workspace.
Previously, a metadata callback retained the earlier locked scope: the list arrived, but its receipt
could not start name verification, leaving the page in its loading state.

## Changes

- Recreate the metadata read callback when the workspace scope changes, preserving its existing
  freshness checks, original Worker verification and Owner/unlock-generation cancellation fences.
- Keep read receipts and decrypted names from an obsolete scope from completing the current list.

## Validation

- Actual combined task hooks and Task Center view reproduce the old failure and cover restoration
  from checking/locked states, pending overview cancellation and late Worker success/failure across
  Owner, lock and unlock-generation changes.
- Focused task regressions, TypeScript and formatting checks pass. All 13 Owner runtime inputs are
  unchanged; this patch does not change cloud configuration or request budgets.
