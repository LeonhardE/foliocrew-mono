# Verify User recovery pages inside the Owner Worker

Date: 2026-11-19

## Summary

The warm Owner session can verify nonce-bound recovery evidence and read pages toward a fixed, independently verified User registry target.

## Changes

- Bind the request to the existing Owner, Root, archive, device pair, and trusted source selection digest.
- Verify bounded, contiguous signed pages without committing a new local pin or granting authority to an intermediate page.
- Require a full refresh for archive, source, or registry epoch changes. Carry account and session cancellation through each read.

## Validation

- Worker integration tests cover nonce replay, rollback, source changes, page scope and signature tampering, fixed targets, expiry, lock cancellation, and unchanged persisted pins.
- Run `npm run check`.
