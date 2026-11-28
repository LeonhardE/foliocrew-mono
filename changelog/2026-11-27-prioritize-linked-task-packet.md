# Prioritize the linked task in its overview

Date: 2026-11-27

## Summary

The Agent Hub overview can deliver the encrypted body of the task a user opened as its first packet.

## Changes

- Accept an optional preferred task ID within the existing four-packet request. Selection uses the current visible task list and keeps the existing signature, lifecycle and byte checks.
- Keep the original packet order for requests without a preference or with an unknown or hidden task.

## Validation

- Task overview tests cover priority beyond the first four tasks, matching and stale cached versions, missing and trashed tasks, response size limits and existing clients.
- Repository-wide validation uses `npm run check`.
