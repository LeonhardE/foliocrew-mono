# Read a verified task's run state and history together

Date: 2026-11-27

## Summary

Opening a verified task now loads its execution state and manual run history in one request. This removes a duplicate User vault authority read from the normal task-link path.

## Changes

- Request the combined read after verifying the task body when the selection needs both state and history. Keep the ordinary detail path for selections that already share its read.
- Check the authenticated owner, vault, task, history summaries and reported active executors. Verify the task state and check the local encrypted outbox before enabling run actions.
- Use the individual endpoints when an older Hub declines the new request or the combined payload exceeds its size limit. Preserve the original read budget and the independent checks performed when starting a run.
- Keep each response bound to its selection. Switching away and returning while a previous read is in flight starts a fresh visit.

## Validation

- Tested the actual browser/proxy request, summary ownership and task binding, and older server and oversized responses.
- Exercised the selected-task hook with delayed reads, selection changes, permission denials, malformed data and run checks.
- Ran the full repository check.
