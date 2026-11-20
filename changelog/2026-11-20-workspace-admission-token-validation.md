# Bound workspace admission token validation

Date: 2026-11-20

## Summary

Validate the compact token structure in linear time before decoding Firebase callbacks.

## Changes

- Check the three nonempty base64url segments directly for both callback and workload tokens.
- Keep signature and identity verification in the existing Firebase SDK.

## Validation

- Six Firebase admission tests.
- Repository-wide `npm run check`.
