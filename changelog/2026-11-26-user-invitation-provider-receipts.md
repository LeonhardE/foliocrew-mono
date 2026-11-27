# Invitation delivery receipts during erasure

Date: 2026-11-26

## Summary

User Service retains a successful provider receipt for the same invitation when its delivery overlaps a retry or revocation. Operators receive an explicit reminder to reconcile all retained invitation mail with the provider before closing an erasure request.

## Changes

- Match late responses to the original invitation's provider idempotency key. A successful delivery can resolve an uncertain retry. A revoked invitation keeps its status, and a replacement invitation cannot inherit a prior recipient's receipt.
- Preserve the database name and list of known message IDs in the read-only erasure output and identify the required provider-side check. Document how to handle reissued, manually sent and unconfirmed deliveries, including when a mailbox has changed owners.

## Validation

- Passed 20 invitation, ownership and erasure tests, including a local Firestore emulator. They cover revocation during sending, overlapping retries, reissued invitations and completion after physical deletion.
- Ran the updated operator output through the existing erasure coordinator for both User databases with synthetic responses. Repeating the inventory stored a single delivery reference.
