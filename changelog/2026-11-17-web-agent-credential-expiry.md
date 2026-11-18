# Clarify Agent credential expiry and account unlinking

Date: 2026-11-17

## Summary

Agent management shows when an execution credential has expired. An active account link can
still be explicitly unlinked after the credential expires.

## Changes

- Show a past-tense, localized expiry date on current and historical credentials once their
  deadline is reached, including on a card already open at that moment.
- Label account unlinking explicitly. Fully revoked connections have no unlink or resume action.
- Reuse the existing owner revocation API and keep credential expiry read-only.

## Validation

- Tested the second before expiry, the exact deadline, and the following second in English,
  Simplified Chinese and Traditional Chinese for Muse and ChatGPT.
- Checked current, historical, revoked and locked states.
