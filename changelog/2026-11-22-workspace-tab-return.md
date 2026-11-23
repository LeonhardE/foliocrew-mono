# Keep workspace pages ready when returning to the tab

Date: 2026-11-22

## Summary

The workbench reuses verified display state for 30 minutes during the same login and unlock session. This covers the Resource Library, Task Center, reports, Agent management, and account display settings on the Market and Settings pages.

## Changes

- Preserve the selected holdings snapshot and import preview, task editor, report list and selection, and completed catalogue and preference reads on ordinary tab returns.
- Mask private displays and cancel pending work while hidden. Lock, logout, changed authority, and expired state require fresh verification.
- Keep explicit refresh, signed writes, and scheduled price reads independent of the display window.

## Validation

- Cover tab return, the 30-minute boundary, private display masking, pending requests, and lock and Owner transitions.
- Run the repository checks.
