# Brand the native account consent page

Date: 2026-11-22

## Summary

The first-party account consent window uses Foliocrew branding and offers a way back to the Agent when an embedded browser needs a user gesture to follow the OAuth callback.

## Changes

- Show an explicit return link only after the bridge validates the registered callback and the Owner confirms the account. Attempt the automatic return in the original consent window.
- Give the Agent the pairing and activation instructions directly so the Owner can focus on reviewing access.
- Avoid returning expired, superseded, or redeemed codes from a reopened approval. Record closed rejection reasons without logging credentials or user information.

## Validation

- Check distributed assets and the signed branded route, including the existing exact callback and bridge boundaries.
