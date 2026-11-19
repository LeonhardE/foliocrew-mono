# Read preserved archive lifecycle history from User

Date: 2026-11-19

## Summary

Keep the original encrypted Passkey archive, signed lifecycle commands, and original receipts readable after the User handover.

## Changes

- Verify the original archive chain and pair it with the current User registry for the authenticated Owner.
- Return only the signed original checkpoints required to verify retained operations, alongside an exact scoped receipt path.

## Validation

- Exercise a signed historical authorization and revocation, exact receipt readback, and account isolation in SQLite.
