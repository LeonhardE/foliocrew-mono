# Allow an owner to permanently delete a task in the recycle bin

Date: 2026-11-26

## Summary

The owner can end a trashed task’s recovery period by signing a separate purge command.

## Changes

- Require the current task revision and lifecycle epoch for an explicit purge.
- Retain the 30-day window for restore and automatic cleanup.

## Validation

- Exercised early purge, incorrect action, stale command, active task rejection and attempts to restore a terminal task.
