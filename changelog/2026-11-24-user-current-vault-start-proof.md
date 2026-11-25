# Reuse the verified start when opening the current vault

Date: 2026-11-24

## Summary

The current-vault read resolves the vault and archive baseline from the
installed handover receipt and its matching head in one transaction.

## Changes

- Remove the separate head lookup before reading the registry start.
- Extend the verified first bundle to the current registry using the proof
  from this request. Read the current head and source index again to confirm
  the verified snapshot, and keep all archive validation and lifecycle checks.

## Validation

- Exercise the Firestore read sequence and a head change between registry
  verification and the final source index read.
- Run the User service tests and repository check.
