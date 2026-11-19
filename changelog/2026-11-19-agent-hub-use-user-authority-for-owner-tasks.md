# Owner task writes verify current User authority

Date: 2026-11-19

## Summary

Use the transferred workspace's current signed User proof for ordinary encrypted Owner task writes and retain immutable task history.

## Changes

- Check the current User signing registry and holdings binding before a new task commit.
- Preserve original Owner task reads and operation receipts through their retained signing proof.

## Validation

- Exercise a new signed submission, an old checkpoint, a source retirement before commit, and original task readback in SQLite.
