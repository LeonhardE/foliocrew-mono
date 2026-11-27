# Sync saved YouTube follows with authorized Agents

Date: 2026-11-24

## Summary

A confirmed YouTube follows save queues a separate encrypted update for Agents
with continuing access to the list. The saved list remains available while the
update is in progress.

## Changes

- Read the current revision once, check the source and each active recipient,
  and verify the catalogue again before encrypting each copy.
- Record the expected next revision before a changed list is saved. Reopening
  and unlocking can recover a committed update even if its response was lost.
  Retry uses the existing sealed publication and receipt when available.
- Display update status and allow retry from the YouTube follows view.

## Validation

- Exercise revision checks, recipient grants, the original publication recovery
  path, the durable pointer, and the actual list save callback.
