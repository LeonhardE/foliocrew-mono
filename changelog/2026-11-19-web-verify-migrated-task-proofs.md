# Verify tasks against the migrated registry

Date: 2026-11-19

## Summary

Use the signed User registry start when opening an accepted task, preparing task controls, and verifying holdings source changes.

## Changes

- Anchor new task and persistent Owner proofs at the verified registry start and preserve the original sequence numbers.
- Select historical snapshot prefixes by sequence relative to that start.
- Use the same verified sequence for signed source controls and recovery of pending uploads.

## Validation

- Cover signed task write and readback, rejection of a substituted old proof, a subsequent Task Center control, and signed holdings source creation in a transferred vault.
