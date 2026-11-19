# Proxy the signed User private resource handover

Date: 2026-11-19

## Summary

Add the fixed same-origin Web transport for checking a prepared handover,
submitting the original Owner-signed packet, and reading the current signed
registry start with a fresh nonce.

## Changes

- Verify the exact Owner scope and use separate verified Web workload
  identity at the pinned User origin.
- Close request and response shapes and check the original signed-input
  fingerprint on the receipt.
- Give the transition bundle its own byte ceiling. Recovery reads retain
  their existing smaller request limit.

## Validation

- Check Owner scope, nonce and receipt mismatch, disabled access and rejection
  of extra request fields.
- Run the repository-wide checks.
