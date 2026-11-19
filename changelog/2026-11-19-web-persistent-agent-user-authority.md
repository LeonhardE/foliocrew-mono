# Persistent Agent approvals use the current User authority

Date: 2026-11-19

## Summary

Use the verified current User authority for Agent approval and encrypted holdings publication in a transferred workspace.

## Changes

- Route the signed credential directory update through User. Resume the original approval after a lost directory acknowledgement and verify the resulting signed head before sending the Agent command.
- Synchronize a holdings publication with the source-scoped Portfolio delegation used by the ordinary holdings flow.

## Validation

- Exercise a lost append acknowledgement, a different signed readback, and scoped snapshot publication.
