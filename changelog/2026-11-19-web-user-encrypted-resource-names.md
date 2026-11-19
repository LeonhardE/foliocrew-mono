# Route encrypted names to User after handover

Date: 2026-11-19

## Summary

Read and rename holdings aliases through the transferred account's User authority.

## Changes

- Bind the User proxy to the exact Owner, vault, source and original operation.
- Discard the legacy name display state across the handover and keep Worker-side signature, decryption and receipt checks.

## Validation

- Exercise selected Owner routing, stable operation binding and rejection of a foreign encrypted reply.
