# Resume User list writes on the named database

Date: 2026-11-19

## Summary

Resume the existing User list writer after authenticated verification of the named database.

## Changes

- Remove the temporary write pause while keeping User list data and receipts in `user-data`.

## Validation

- Review the exact saved configuration change and verify a post-cutover write survives rollback to a compatible named-database revision.
