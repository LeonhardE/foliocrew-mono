# Freeze legacy Agent authorization during private resource handover

Date: 2026-11-19

## Summary

Bind new legacy Agent authorization and credential admission to the account
fence while preparing a private resource handover.

## Changes

- Stop new native approval and reject exchange, refresh, and access when the
  account is frozen.
- Check the same fence before new credential setups, offers, and Owner
  approvals. Preserve the original callback and receipt where already recorded.
- Continue Owner-side disconnect and preserve independent account behavior.

## Validation

- Exercise frozen legacy authorization and revoke in the native transport
  regression suite.
- Run the repository-wide checks.
