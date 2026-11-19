# Bind Portfolio delegation to transferred User authority

Date: 2026-11-19

## Summary

Allow the authenticated owner of a transferred vault to request short-lived
delegation for Portfolio to read one current source from User.

## Changes

- Bind the delegation to the exact owner, vault, source, nonce, minimum
  registry epoch, Portfolio workload, and User endpoint.
- Require the durable writer transfer for the configured account before signing.
- Keep the new endpoint disabled until explicitly enabled.

## Validation

- Exercise the real signing boundary with a synthetic KMS key and verify denial
  for frozen, unselected, or otherwise mismatched scopes.
- Run repository-wide checks.
