# Verify transferred archive history across the signing boundary

Date: 2026-11-19

## Summary

Anchor transferred archive receipts to the same Root across the original and current signing registries.

## Changes

- Accept the larger bounded history only with an independently verified current User registry cursor.
- Preserve the original legacy verifier and its 32-checkpoint limit.

## Validation

- Verify an original receipt at checkpoint 33 and reject a broken chain, an old authority cursor, and a legacy over-limit request.
