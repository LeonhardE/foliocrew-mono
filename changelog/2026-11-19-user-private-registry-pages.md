# Serve bounded private registry pages from User

Date: 2026-11-19

## Summary

User can stage the original signed registry history and serve fixed-target pages to the authenticated Owner.

## Changes

- Store verified bundles under the exact vault, epoch and sequence. Preserve their original bytes on replay.
- Read a bounded range tied to the current Owner recovery head and exact prior page. Continue using the existing activation boundary.

## Validation

- Tests cover original-byte replay, mismatched bases and targets, account isolation, and a 33-bundle chain verified through the existing shared contract.
