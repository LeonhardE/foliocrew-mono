# Verify report source decision requests

Date: 2026-11-19

## Summary

Add a shared Hub-to-User authentication profile for an individual report source-decision request.

## Changes

- Verify the exact Hub workload, pinned Hub signature, purpose, audience and expiry.
- Bind the signed Owner and attempt to the canonical private resource request.

## Validation

- Signed synthetic vectors exercise exact matches and reject reuse with changed source inputs, identity, attempt or token profile.
