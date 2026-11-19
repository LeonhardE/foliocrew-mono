# Store encrypted resource names under User authority

Date: 2026-11-19

## Summary

Read and write holdings aliases in the same User scope as their current source registrations.

## Changes

- Validate the current signed registry and commit each alias revision and original acknowledgement together.
- Hide retired aliases from the directory and retain exact original acknowledgements for the authenticated Owner.

## Validation

- Exercise ciphertext versions, a retired source, exact replay, and the dual-authenticated Owner routes in SQLite.
