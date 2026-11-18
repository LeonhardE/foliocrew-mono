# Reuse task results already shown in this session

Date: 2026-11-17

## Summary

Opening a task with historical runs no longer delays the next task by rereading report lists that already contain those results.

## Changes

- Check completed runs against the current account’s loaded results before refreshing the three report feeds.
- Allow a pending feed read to finish before checking new result IDs. A previously unseen result still triggers a refresh, and a failed refresh remains available for manual retry.

## Validation

- Tested a historical run from a shared task overview, results arriving during a feed read, unread counts, failed reads and account changes.
