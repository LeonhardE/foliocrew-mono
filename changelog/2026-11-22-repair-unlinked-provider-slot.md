# Reconnect an unlinked Agent account

Date: 2026-11-22

## Summary

A new Agent connection can replace an unlinked account after vault transfer, including when the old account was unlinked after the transfer.

## Changes

- Keep the existing slot revision and last credential in the approval review when its former account has been revoked.
- Verify that fresh signed activation succeeds in this state and that replay returns the original receipt.

## Validation

- Run the provider slot transaction suite and the repository checks.
