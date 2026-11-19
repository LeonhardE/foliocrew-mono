# Exempt encrypted User archive records from indexing

Date: 2026-11-19

## Summary

Keep the encrypted archive and signed lifecycle record out of field indexes in the named User database. Owner archive reads use the document ID.

## Validation

- Verify the exact collection, field and database in the Terraform foundation test, with retention policies preserved.
