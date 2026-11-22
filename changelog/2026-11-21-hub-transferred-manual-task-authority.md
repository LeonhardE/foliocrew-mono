# Use the current User writer for transferred manual tasks

Date: 2026-11-21

## Summary

Task Center uses the current verified User registry for assignments, manual
requests, and native pickup after an Owner transfers the vault.

## Changes

- Resolve the authoritative registry before the transaction and recheck its writer fence inside it.
- Verify manual pickup against the original signed sequence even if the active history starts after sequence one.

## Validation

- Signed manual intent, retry, native pickup and original Run on a transferred synthetic vault.
