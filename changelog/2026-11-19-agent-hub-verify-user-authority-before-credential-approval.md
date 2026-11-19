# Issue new Agent credentials from current User authority

Date: 2026-11-19

## Summary

Use the transferred account's verified User registry for credential setup,
owner approval, and new provider connections.

## Changes

- Verify the native connection against the same completed authority transfer.
- Fetch scoped User evidence before the Hub transaction and recheck its local
  transfer marker within the transaction.
- Preserve original credential and provider receipts after transfer.

## Validation

- Exercise the scoped setup, approval, and exact receipt paths.
- Run repository-wide checks.
