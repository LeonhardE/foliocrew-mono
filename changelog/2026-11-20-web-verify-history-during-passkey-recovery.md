# Verify historical key proofs during Passkey recovery

Date: 2026-11-20

## Summary

Independent recovery can reopen a renewed vault whose registry moved to the User service.
The replacement Passkey still protects the original vault root and retained historical keys.

## Changes

- Give the isolated recovery Worker the same signed original registry proof transport used by
  normal unlock so it can verify historical keys omitted from the active registry.
- Verify recovery with a separate browser store, a synthetic save receipt, and a second unlock
  using the replacement credential.

## Validation

- The regression reproduced the untrusted vault error before the fix. Recovery and repository
  checks cover the corrected flow.
