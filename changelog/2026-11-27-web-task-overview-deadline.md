# Recover the task list and run controls after slow reads

Date: 2026-11-27

## Summary

Opening an unlocked task could show a list error and leave its run button unavailable while the
server was still preparing a successful response.

## Changes

- Allow the task overview to complete within its own bounded proxy and browser deadlines.
- Keep time for the existing task-list fallback when the overview returns a 503.
- Distinguish a list timeout from a confirmed empty list. Retrying also rechecks failed run
  capabilities and report reads while keeping actions disabled until the service confirms them.

## Validation

- Exercised a 12.8-second successful overview, a delayed 503 followed by a successful list read,
  a genuine timeout and an explicit retry that restores the task list and run controls.
- Ran the repository checks with `npm run check`.
