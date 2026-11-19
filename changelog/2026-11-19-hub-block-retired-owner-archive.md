# Close legacy Owner archive reads after the User handover

Date: 2026-11-19

## Summary

Stop returning the old encrypted archive once the durable account fence records the completed handover.

## Changes

- Use the same storage transaction for the read gate and the legacy archive response.
- Allow the existing original Passkey review during preparation and retain signed operation receipts.
- Join the migration fence to the existing Agent display batch so the storage read phases stay bounded.
- Reuse the shared read-only removal outcome contract.

## Validation

- Exercise a frozen account, a transferred account, legacy enrollment replay, and unaffected accounts.
