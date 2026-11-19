# Verify the signed User registry epoch in the Owner Worker

Date: 2026-11-19

## Summary

Let the Owner Worker verify a User registry start against the original Root
and fresh account-bound recovery evidence.

## Changes

- Check the original archive, preceding checkpoint, exact nonce and unchanged
  authorized Owner device keys.
- Continue subsequent bounded pages on the verified epoch and fixed target.
- Keep the verified candidate separate from installed authority until the
  full cutover applies it.

## Validation

- Exercise the real browser Worker against the same-Root signed packet,
  rejected altered evidence and preserved local pins.
- Run the repository-wide checks.
