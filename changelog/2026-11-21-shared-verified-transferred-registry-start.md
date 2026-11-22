# Verify an Owner-signed registry start after a vault transfer

Date: 2026-11-21

## Summary

The shared verifier can verify the active history of a transferred vault from its
Root-signed Owner-only start.

## Changes

- Verify the transition, first checkpoint, and continuity against the pinned Root, start, and head.
- Keep the original sequence-one verification for callers without transfer proof.

## Validation

- Synthetic signed old and transferred histories, incomplete proofs, and unauthorized keys.
