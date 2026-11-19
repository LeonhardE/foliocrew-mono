# Use current User authority in native Agent execution

Date: 2026-11-19

## Summary

Verify current transferred authority for native Agent task, Run, and report operations.

## Changes

- Require the exact new connection and User signing registry when serving current Agent inputs or creating a Run.
- Recheck current holdings bindings and the short-lived User proof after producer reads.
- Use the User report decision before committing a result in Hub and keep the original committed receipt.

## Validation

- Exercise signed Agent requests, frozen inputs after source retirement, and the original report receipt in SQLite.
