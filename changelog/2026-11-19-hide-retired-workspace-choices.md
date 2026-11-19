# Hide retired workspace choices

Date: 2026-11-19

## Summary

The holdings picker hides deleted source incarnations. Muse and ChatGPT use the same unconnected state after their previous accounts are unlinked.

## Changes

- Show an empty holdings state when all sources are deleted and keep the original deletion recovery action available while confirmation is pending.
- Exclude revoked provider connections from management cards and suppress review prompts backed only by confirmed revoked connections. Continue to surface active credentials and unresolved provider state.

## Validation

- Holdings source picker and provider grouping regression tests cover mixed and empty inventories, pending deletion, and revoked provider slots.
