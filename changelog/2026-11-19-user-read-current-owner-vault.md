# Serve the transferred Owner vault for a cold start

Date: 2026-11-19

## Summary

Read the scoped vault and original sealed archive from User with the current
signed registry evidence needed by the Owner browser.

## Changes

- Select the vault through the verified account's installed handover.
- Verify the archived envelope against the installed boundary.
- Bind the current response to a fresh Owner request and expose only the
  current source index.

## Validation

- Verify the original sealed archive and exact current registry evidence.
- Run repository-wide checks.
