# Sync saved holdings with authorized Agents

Date: 2026-11-24

## Summary

While the workspace is open and unlocked, a confirmed holdings save starts a separate
encrypted update for Agents with continuing access to that holdings source.

## Changes

- Use the latest committed holdings revision, check the exact source and recipient,
  and retain the existing permission and publication receipt checks.
- Show a separate status for the update and allow retry without saving the holdings again.
- Recover an existing publication using its receipt, or preserve an older sealed operation
  when a newer owner-signed snapshot has superseded it.

## Validation

- Cover recipient and source scoping, exact pending operation recovery, and repository checks.
