# Finish Agent connections from the current provider card

Date: 2026-11-22

## Summary

First-time Agent connections distinguish account confirmation, OAuth return, and signed credential pairing.

## Changes

- Allow a signed-in Owner with an existing vault to confirm the account and return to the original authorization window. Passkey unlock remains part of signed pairing.
- Show the next account-link or pairing action on the current provider card and remove the historical connection list from management.
- Load the pairing review automatically in an unlocked workspace and leave the final choice to the Owner.

## Validation

- Exercise account confirmation with a locked vault, pending OAuth, pairing after token exchange, and current-only management.
