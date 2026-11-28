# Read task controls and manual run history together

Date: 2026-11-27

## Summary

The task detail service can return the controls and manual run history needed to display an
already-opened task in one authorized read.

## Changes

- Add an opt-in display mode to the existing private task detail endpoint.
- Check current Owner authority and task visibility once for both sections and return the original
  state and run summaries from the same transaction.

## Validation

- Compared responses with both original endpoints using empty, waiting and running histories.
- Tested changed access, task visibility, read failures, retry and the response size limit.
