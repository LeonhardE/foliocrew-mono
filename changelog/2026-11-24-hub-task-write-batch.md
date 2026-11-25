# Batch transactional reads during task saves

Date: 2026-11-24

## Summary

Encrypted task saves group four task state reads into a single database request
per transaction attempt.

## Changes

- Fetch the index, head, operation receipt, and cancellation ledger together
  after the authority and task visibility checks.
- Keep the preflight and final transactions, original row validation, source
  checks, cancellation handling, and atomic commit.

## Validation

- Use the Firestore SDK fixture to verify the same four rows are read in each
  separate transaction. Exercise competing edits, replay, and source revocation.
- Run the Agent Hub service tests and the repository check.
