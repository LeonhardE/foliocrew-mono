# Show progress for the confirmed manual run

Date: 2026-11-27

## Summary

A manual run that cannot start now explains whether the request was sent. Its progress dialog shows the request identified by the receipt or the active run found during confirmation.

## Changes

- Keep the dialog closed if a preflight read fails. Show normal progress while sending. Offer recovery for the original request only after submission ends without a confirmed receipt.
- Tie progress, cancellation and the Agent continuation to the selected request even after history changes.

## Validation

- Ran the task center hook, editor and rendering regression suites, including failed preflight, a lost POST, a concurrent active run and later changes to run history.
