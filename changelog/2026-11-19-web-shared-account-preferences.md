# Share one signed-in preference read

Date: 2026-11-19

## Summary

Web shares one Config response for UI, language, and currency preferences in the current signed-in session.

## Changes

- Share the initial request and short-lived memory snapshot while respecting account changes and each caller's cancellation.
- Recover unavailable settings and write conflicts with a fresh unified read. Keep the independent settings writes and validation.

## Validation

- Auth and settings tests verify transport coalescing, per-section availability, exact scope, and independent writes and conflict recovery.
