# Preserve original vault operations during User migration

Date: 2026-11-19

## Summary

The migration baseline can retain the original typed operation records and source invalidation acknowledgements for later compatible replay.

## Changes

- Keep original document keys, request fingerprints and exact typed values in an immutable, Owner-bound record.
- Bind source acknowledgements to the original incarnation, epoch progression, operation and fingerprint.
- Reuse the User create-only archive storage without installing any live authority.

## Validation

- Exercise repeat staging, preservation of original typed fields and rejection of an altered acknowledgement.
- Rehearse with the 35 records in the approved account and run the repository checks.
