# Commit transferred Owner key renewals in User

Date: 2026-11-19

## Summary

Allow the transferred Owner to renew eligible keys with the original Root and an encrypted archive rewrap.

## Changes

- Validate the signed renewal pair and the exact current key and archive versions.
- Commit the new registry entry, archive lifecycle and immutable receipt in one User transaction.
- Keep previously accepted legacy renewal receipts readable from the verified handover evidence.
- Keep the scoped renewal writer disabled pending its compatible Web client.

## Validation

- Exercise fresh successor keys, same-Root archive rewrap, exact receipt replay and interrupted writes.
