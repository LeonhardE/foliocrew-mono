# Stop reading foreground reports in task feeds

Date: 2026-11-19

## Summary

Use persistent results for Hub's combined task overview and per-task history.

## Changes

- Stop loading foreground heads, indexes and cursors in the task overview.
- Page current and previous persistent records and treat an existing foreground cursor as terminal.

## Validation

- Task snapshots and paging tests cover retained persistent history, read budgets, owner scope and independence from old inbox rows.
