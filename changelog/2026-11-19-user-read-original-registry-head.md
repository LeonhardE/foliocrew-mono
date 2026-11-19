# Read the signed original registry head

Date: 2026-11-19

## Summary

Return the exact terminal registry bundle as one bounded read for the owner of a transferred vault.

## Changes

- Scope the proof to the owner proxy, the authenticated account and the original head committed by the signed transition.
- Read only the final stored original bundle. Existing paged recovery stays available for earlier trusted checkpoints and historical dependencies.

## Validation

- Exercise the terminal bundle, wrong target, unrelated account and anonymous route.
