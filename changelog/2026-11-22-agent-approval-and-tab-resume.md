# Agent approval and tab return

Date: 2026-11-22

## Summary

The Agent authorization form opens without waiting for connection inventory to render. Returning from Muse to an unlocked Agent tab keeps the form and the last verified connection status.

## Changes

- Load independent approval reads concurrently. Revalidate the reviewed state at submission.
- Show progress during approval, separate the advanced options from the confirmation buttons, and tell the user where to continue after the approval is saved.
- Keep the same Agent display on ordinary tab returns within 30 minutes of verification. Account changes, explicit locks, and signed submissions still use their existing verification paths.

## Validation

- Run the Agent and vault visibility regression tests and the repository checks.
