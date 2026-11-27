# Coordinate account erasure and verify restored data

Date: 2026-11-26

## Summary

A restricted operator can track one verified account request across the application stores
and apply those requests to an isolated recovery database before it returns to use.

## Changes

- Reuse service-owned inventory and removal commands, including legacy User storage.
- Preserve the identities needed for restore checks and delivery follow-up until case closure.
- Verify the Firebase and Firestore completion conditions and remove identifying case records.

## Validation

- Regression tests cover mismatched subjects, interrupted operations, incomplete adapter results
  and the detection of retained data in a restored copy.
