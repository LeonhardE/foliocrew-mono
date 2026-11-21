# Reuse the provider slot version during migrated activation

Date: 2026-11-21

## Summary

An Owner can activate a new Agent for a transferred vault when the previous provider slot still references a revoked connection from the earlier authority.

## Changes

- Use the actual slot version and generation for activation review and its transaction. Exclude the earlier credential and grants from the active review.
- Keep earlier credentials and connection records intact. Refuse the replacement while an out-of-scope connection still has an active status.

## Validation

- A signed regression reproduces the released conflict and verifies successful activation, monotonically increasing versions, an unchanged old connection, and replay of the original receipt.
