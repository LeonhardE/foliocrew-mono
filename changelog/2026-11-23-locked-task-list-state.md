# Wait for unlock before loading the task list

Date: 2026-11-23

## Summary

The task page now shows the Passkey prompt while locked and loads the list after unlock.

## Changes

- Scope task list and resource reads to the unlocked workspace. Cancel pending reads when that scope changes.
- Keep real unlock failures visible. Show list failures and their retry action in the unlocked task view.

## Validation

- The task overview and UI regressions reproduce the locked-state error on the previous version and verify successful discovery after unlock.
