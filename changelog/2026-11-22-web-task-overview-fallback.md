# Recover task results from a temporary overview failure

Date: 2026-11-22

## Summary

When the shared task overview returns HTTP 503, the workbench loads tasks, report results, and executor labels through the existing individual reads.

## Validation

- The Web regression starts from one HTTP 503 and verifies that the task and result views recover with one pass through the individual reads.
- Existing coverage checks malformed summaries, other HTTP errors, explicit refreshes, and obsolete sessions.
