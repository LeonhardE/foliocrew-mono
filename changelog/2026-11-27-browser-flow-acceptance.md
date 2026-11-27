# Verify the user interface and network together

Date: 2026-11-27

## Summary

Browser acceptance now covers the visible workflow, its full network trace, and the result on the original item. A successful backend write alone leaves the workflow unverified.

## Changes

- Record intermediate UI errors, failed requests, request counts, timings, redundant reads, and polling after completion.
- Require a fresh passing run after a failure. For closed-page flows, verify the trigger, original result, and approval behavior.

## Validation

- Checked the criteria against a task save that persisted its rule despite a visible error and failed network requests.
