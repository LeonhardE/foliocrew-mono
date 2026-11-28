# Allow cold starts during manual task confirmation

Date: 2026-11-27

## Summary

Foliocrew can wait longer for the current task definition and run history when the services handling a manual run need to start.

## Changes

- Give the two authenticated reads a total of 20 seconds at the web proxy and 24 seconds in the task center, including authentication and reading the response.
- Poll an active manual run five seconds after the previous progress check finishes. Polling starts after the selected task’s initial history is available and pauses while the tab is hidden.
- Continue to cancel pending reads when the caller leaves. A timeout or cancellation before confirmation cannot submit the run.

## Validation

- Cover both reads returning after the previous deadline, caller cancellation, total deadline expiry, and the original timeout for other requests.
