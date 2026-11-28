# Reduce the wait for linked task details

Date: 2026-11-27

## Summary

A task opened by a direct link can reuse the first display verification immediately after unlock.
Its execution controls and run history load together once the encrypted task is verified.

## Changes

- Keep deep links independent of the first list page. Reuse an already available, matching
  overview packet or immediately fetch the linked task through its original authorized reader.
- Reuse the existing five-second, single-use verified User vault receipt for automatic link
  opening. For a selection from the list, start the independent User vault and Hub detail reads
  together and require both checks before showing the task.
- Bind the concurrent run-history read to the same selection as the verified controls. Keep writes
  and manual runs on their existing authorization and preflight paths.

## Validation

- Exercised delayed and unavailable overviews, a linked task outside the first page, overlapping
  User and Hub reads, a changed root, navigation, and history retries.
- Ran the repository check.
