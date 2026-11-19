# Hide retired Agent connection details after handover

Date: 2026-11-19

## Summary

Show only current Muse and ChatGPT connections for the workspace that moved to User.

## Changes

- Use the verified User transition marker to filter the Agent display and its provider selection hints.
- Leave original receipts in place and let the browser read the current vault directly from User.

## Validation

- Exercise a revoked slot, older connections for both providers, and a current connection in the synthetic Firestore fixture.
