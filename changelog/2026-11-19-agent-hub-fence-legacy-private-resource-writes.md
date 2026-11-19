# Fence legacy private resource writes by account

Date: 2026-11-19

## Summary

Prepare each account for a single private resource writer during the User
handover. A durable Hub fence stops new legacy commitments for that account
while permitting reads and exact operation replays.

## Changes

- Read the account fence in the same transaction as new vault, registry,
  archive, renewal, source and private display-name writes.
- Return the original operation outcome for replays and retain independent
  writes for accounts without a fence.

## Validation

- Exercise frozen vault and source writes, exact replay, and a second account
  in the Hub regression tests.
- Run the repository-wide checks.
