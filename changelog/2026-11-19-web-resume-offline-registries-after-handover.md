# Resume offline devices across a same-Root handover

Date: 2026-11-19

## Summary

Let a returning device connect its trusted old browser pin to the exact original checkpoint signed by the Owner.

## Changes

- Verify only missing old bundles in the encrypted Worker. Keep the old on-disk pin through missing or altered pages.
- Commit the current registry epoch only after the original archive unlock and the current authority verification.

## Validation

- Exercise a multi-page original chain and reject a skipped original checkpoint using the actual Worker and IndexedDB fixture.
