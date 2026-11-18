# Read a selected task and its executor together

Date: 2026-11-17

## Summary

Opening a task can use one private Hub response for the encrypted description, execution settings and original executor attribution. The browser also requests the current vault independently and verifies the data before presenting it.

## Changes

- Share one bounded query between the task description and executor. Reuse current packets and keep the most recently verified task details available for quick navigation.
- Start the run-status check as soon as the two primary reads are in flight. Existing and pending runs still require their own action checks.
- Read an individual section through its original endpoint when the Hub explicitly marks that section unavailable. Discard late responses after a selection or scope change.

## Validation

- Checked the browser, web proxy and hook paths with synthetic tasks, including expired display receipts, legacy executors, partial reads, local actions and selection changes.
