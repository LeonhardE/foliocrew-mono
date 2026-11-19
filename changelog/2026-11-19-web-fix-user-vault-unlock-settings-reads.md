# Restore migrated vault unlock and limit Settings requests

Date: 2026-11-19

## Summary

Vaults that retained historical keys before migration can unlock with the same Passkey. The Settings route no longer starts a watchlist read.

## Changes

- Restore original Root-signed certificate evidence at the signed migration boundary when archived keys are outside the current registry. Reuse verified evidence in the active worker.
- Start the account watchlist on Markets or Resources and retain the loaded list across navigation.

## Validation

- Cover a Passkey archive with a pre-migration key renewal, substituted registry pages, and deferred watchlist loading.
