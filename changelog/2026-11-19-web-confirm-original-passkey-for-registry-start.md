# Confirm the original Passkey for a new registry start

Date: 2026-11-19

## Summary

The encrypted Owner Worker can review the keys for a new same-Root registry start and produce a signed packet after fresh confirmation with the existing Passkey.

## Changes

- Bind the review to the verified vault, archive and registry. Keep only current Owner device and recovery keys in the new start.
- Confirm the original archive locally using fresh Passkey material. The signed packet carries public evidence and keeps installed local pins intact.

## Validation

- Exercise expired review, wrong Passkey, replay rejection, and stable local pins inside the Worker.
- Verify the browser-signed packet with the shared Python transition verifier and run the repository checks.
