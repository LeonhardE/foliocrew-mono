# Shorten the verified task save path

Date: 2026-11-24

## Summary

Start loading the current task as soon as the write returns a structurally matching response. The read overlaps authentication and decryption of the saved response.

## Changes

- Verify the saved response before handling the current read outcome, then independently verify the current task before accepting it. The editor uses the latest verified version, including a later version committed during the save.
- Keep the forced vault refresh, original write, current-task read, existing conflict checks, and exact retry packet handling.

## Validation

- Controller tests cover read and verification concurrency, adoption of a newer version, error precedence, and retention of the sealed draft and retry packet on failure.
