# Verify preserved archive history from User

Date: 2026-11-19

## Summary

Read the transferred vault's original Passkey archive lifecycle and matching operation receipts through User.

## Changes

- Bind the browser's read to its current account, vault, and fresh request nonce.
- Verify original archive commands against the signed checkpoint chain named in the same-Root transition before accepting any lifecycle summary.

## Validation

- Exercise original archive commands and rejection of an incomplete checkpoint proof with the actual Worker core.
