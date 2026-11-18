# Include the current vault when opening a task

Date: 2026-11-17

## Summary

Owner clients can retrieve the current vault and the selected task in one request. This frees a
browser request slot for the task's execution history.

## Changes

- Added an optional `includeVault:true` flag to the selected task detail query. It returns the
  complete current vault response and the current task metadata from the same transaction.
- Read current source epochs with the existing task batch. The vault section supports independent
  fallback when a source fails validation or the response exceeds the existing size limit.

## Validation

- Compared the opt-in data with the original vault and task reads, including a changed source epoch.
- Tested the original response shape, owner and visibility checks, isolated failure and size fallback.
- Ran the full repository checks.
