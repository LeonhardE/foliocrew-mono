# Reuse the combined Portfolio view on holdings selection

Date: 2026-11-19

## Summary

Selecting holdings uses the existing combined Portfolio read once the browser verifies the current vault.

## Changes

- Bind the view to the selected source incarnation and verified vault. Preserve exact current-version checks and verified snapshot display.
- Use existing fallback paths for synchronization, oversized views, and unconfirmed operations.

## Validation

- The selection regression verifies one Portfolio view request, the exact selected incarnation, and the resulting source metadata.
