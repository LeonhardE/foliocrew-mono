# Restore task overview packets after vault transfer

Date: 2026-11-22

## Summary

The task overview now carries the verified Owner scope into historical packet checks after the vault writer transfers to User. The signed packets and existing cache checks are preserved.

## Validation

- The regression reads the same original and post-transfer signed packets through both the individual task endpoints and the task overview.
