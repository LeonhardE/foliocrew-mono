# Verify and apply a transferred cloud archive removal

Date: 2026-11-19

## Summary

Support the Owner's signed archive removal, withdrawal, and exact outcome check under User authority.

## Changes

- Atomically publish an empty active archive and its signed removal receipt without changing registry or source identities.
- Allow the signed independent recovery flow to restore an active archive and keep prior removal and withdrawal receipts readable.
- Keep the separate removal route disabled until the compatible browser is deployed.

## Validation

- Exercise removal, read-only outcome checks, withdrawal, failure-only rollback and restoration from an independent authorization.
