# Shorter waits when opening task details

Date: 2026-11-17

## Summary

A task can show its verified description and executor while its manual-run status is still loading. Browsing the overview also skips two requests for information shown in other tabs.

## Changes

- Verify the vault and fetch the encrypted body concurrently when the overview lacks a current copy. Start executor discovery from the selected list entry and tie every response to the current selection.
- Fetch the resource catalogue when creating or editing a task and fetch task-specific report pages when viewing results. Keep the unread counts available in the task list.
- Verify the current run state and pending requests before allowing a manual run. Provide a local retry if that read fails.

## Validation

- Repository checks and focused tests cover scope changes, executor attribution, action readiness, read demand, and overlapping reads.
