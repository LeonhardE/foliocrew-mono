# Complete scoped archive replacement and recovery in Web

Date: 2026-11-19

## Summary

Use User for signed archive replacement and recovery controls after the same-Root handover.

## Changes

- Bind signed writes and their receipts to the selected account, vault, and request.
- Verify an updated archive against the original signed boundary and the full lifecycle in the browser Worker before using it.
- Resume pending archive changes through the current signed history and preserve the ordinary cold-start path for unchanged archives.

## Validation

- Exercise genuine synthetic Root signatures and rejection of altered, incomplete, and rolled-back archive history.
