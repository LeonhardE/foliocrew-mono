# Keep task executors when editing a schedule

Date: 2026-11-27

## Summary

Saving a new time keeps the selected executor eligible to run the task.

## Changes

- Rebind selected executors to the updated rule even when their existing
  credentials and encrypted task publication are unchanged.
- Remove an assignment only when the user deselected it in the editor. A
  concurrent replacement requires another review.

## Validation

- Exercised schedule changes, unchanged schedules, previously stale assignments,
  explicit removal, and concurrent replacement in the task editor tests.
