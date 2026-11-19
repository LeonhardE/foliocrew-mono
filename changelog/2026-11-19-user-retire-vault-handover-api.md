# Retire the completed User vault handover API

Date: 2026-11-19

## Summary

Remove the one-time API for previewing and installing the completed private-vault migration.

## Changes

- Remove both adoption routes, their request and write logic, and their rollout flag.
- Preserve current User access, original operation receipts, and verification of the signed registry start and the original archive.

## Validation

- Verify both retired paths are absent. Cover same-vault recovery, original operation replay, key renewal, and new source registration against transferred fixtures.
