# Preserve the User registry floor when reopening a vault

Date: 2026-11-19

## Summary

Verify a same-Root User registry and keep its epoch in the browser's durable
trust record.

## Changes

- Verify the original sealed envelope, signed transition, current checkpoint,
  and scoped source index before using a User vault.
- Reject a response older than an accepted local registry epoch.
- Install the verified epoch alongside the existing vault pin atomically.
- Use the scoped User registry and Portfolio authority paths for ordinary
  device and holdings operations, including recovery of an unknown receipt.

## Validation

- Exercise the original Passkey and the current epoch in the browser Worker.
- Run repository-wide checks.
