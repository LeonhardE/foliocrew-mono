# Synchronize approved Agent watchlists after saving

Date: 2026-11-24

## Summary

The shared watchlist editor checks for updates to Agent resources after saving in Market or Resources. Existing continuing permissions control recipients.

## Changes

- Request a User Service revision alongside watchlist changes and verify it against the current source catalogue before sealing an Agent update.
- Preserve ordinary watchlist editing during User Service rollout. A response without a revision cannot trigger an automatic publication.
- Keep the last pending revision with the unlocked owner's vault. Resume the original encrypted operation or verify a newer revision before preserving an older operation.
- Show save and Agent synchronization separately in the resource library.

## Validation

- Exercise versioned and legacy CRUD, changed and unchanged revisions, wrong owner and revoked permission, cross-resource isolation, and IndexedDB recovery.
