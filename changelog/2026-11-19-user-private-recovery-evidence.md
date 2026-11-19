# Add a bounded User recovery projection

Date: 2026-11-19

## Summary

The User private resource module can serve a nonce-bound recovery check from a verified current head.

## Changes

- Store the archive boundary, registry head, current Owner device pairs and active source digest in User's storage.
- Add an opt-in Owner endpoint with the existing authentication and no-store response policy. Keep production use gated on the same-database authoritative transition.

## Validation

- User tests cover exact device and account scope, expiration, archive deletion, replay, monotonic updates and one bounded Firestore read.
