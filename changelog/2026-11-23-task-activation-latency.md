# Separate task saving from Agent setup

Date: 2026-11-23

## Summary

Task Center shows when an encrypted task is saved while schedule, Agent access and
resource preparation continue. A setup interruption can be retried on the original task.

## Changes

- Avoid a repeat catalogue request on confirmed creation and overlap independent verification reads.
- Use the exact saved task version and the selected sources during setup. Recover related sealed
  operations by their original receipts and keep source checks before publication.
- Skip intermediate detail reloads during setup and retain the final verified refresh.
- Show only Revoke access on an established, healthy Agent connection. Keep connection renewal
  and continuation available when the corresponding account or credential needs them.

## Validation

- Cover exact pending publication recovery, selected sources and the healthy connection UI.
- Run Web type checks and the full repository check.
