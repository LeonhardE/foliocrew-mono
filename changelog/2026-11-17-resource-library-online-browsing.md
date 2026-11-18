# Keep online resource browsing usable

Date: 2026-11-17

## Summary

An open resource library keeps its confirmed lists available while the browser stays online.

## Changes

- Use receipt age to decide whether a returning view needs another read.
- Preserve revision checks on edits. Retain cached rows and offer recovery after a failed read or loss of connectivity.
- Separate recovery notices from the category controls.

## Validation

- Covered online idle time, offline browsing, reconnect, explicit retry and revision-checked writes in the Web tests.
