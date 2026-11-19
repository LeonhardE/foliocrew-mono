# Advance the transferred Passkey archive in User

Date: 2026-11-19

## Summary

Add a scoped User writer for the encrypted archive and its signed recovery authorizations after the same-Root handover.

## Changes

- Verify the existing lifecycle and current registry before committing an encrypted archive replacement, recovery authorization, or revocation.
- Commit the current archive boundary and lifecycle receipt together. A replay returns the original receipt.
- Return the signed continuation with the current cold-start proof after an archive change.
- Keep the writer disabled pending deployment of the compatible Web reader.

## Validation

- Exercise prior archive readback, archive replacement, recovery authorization and revocation, receipt replay, and stale-write rejection.
