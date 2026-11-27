# Read the assigned Agent's publication when saving a task

Date: 2026-11-27

## Summary

Saving an enrolled task reads the selected Agent's publication directly. An unavailable resource list shows a retry next to the resource picker, so a schedule edit can show its own progress and outcome.

## Changes

- Reuse the task state obtained during this save to locate the publication, verify the signed task state and read the receipt for the selected connection.
- Recheck the task, signed rule, assignment version and publication head before assigning the Agent. Recovering an interrupted task publication reads fresh state. Legacy task management retains its discovery path.
- Keep resource discovery errors visible while selecting resources or opening a task from a resource. Save and activation errors retain their own feedback.

## Validation

- Checked schedule edits, unchanged schedules, concurrent publication replacement, interrupted publication recovery and resource picker feedback.
