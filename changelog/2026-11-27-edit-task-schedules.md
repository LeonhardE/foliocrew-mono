# Save schedules after viewing an existing recurring task

Date: 2026-11-27

## Summary

The task editor can save a changed schedule and create a new recurring task after the user views an existing schedule in the same session.

## Changes

- Populate the schedule editor with frequency, weekdays, local time and time zone. The signer supplies activation time, grace period and daylight-saving rules when it signs each change.

## Validation

- Reproduced the extra fields in both flows through the task wizard and verified the corrected commands.
- Ran `npm run check`.
