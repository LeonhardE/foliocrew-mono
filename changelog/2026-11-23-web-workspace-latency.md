# Reduce workspace page waits

Date: 2026-11-23

## Summary

Start private work when a private page needs it, and recover when tab switching interrupts the initial check.

## Changes

- Open Market without a vault check. Keep the same private session after the first private page visit.
- Resume a cancelled initial vault check when the tab becomes visible. Wait for that check before fetching the task list.
- Show a single transferred holdings source from its direct Portfolio read. Request the resource catalogue when the user needs task selection or when direct source discovery is unavailable.
- Reuse the just-verified vault for the first automatic Agent display after unlock. Keep completed Agent statuses ready during the existing 30-minute display window.

## Validation

- Workspace tests cover deferred startup and sign-out, returning after a cancelled check, direct holdings with on-demand discovery, task list startup, and verified Agent display reuse.
