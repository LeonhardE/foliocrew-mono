# Improve task detail switching and executor feedback

Date: 2026-11-17

## Summary

Reopening a recently viewed task reuses its verified detail in the current unlocked workspace. Executor loading and recovery belong to the selected task.

## Changes

- Reuse a bounded, short-lived detail when the entire task metadata and vault version match.
- Use the original encrypted task packet from the current overview when available, and verify it in the worker.
- Read verified assignments locally from the selected record. For a legacy task, look up its authority and provider without reopening its body.
- Keep historical versions and write-time verification on their existing fresh paths.

## Validation

- Covered switching between tasks, explicit refresh, hidden-page invalidation and late responses in the task controller tests.
- Covered legacy, modern and empty assignments, failed lookups, local retry and switching away from pending reads.
