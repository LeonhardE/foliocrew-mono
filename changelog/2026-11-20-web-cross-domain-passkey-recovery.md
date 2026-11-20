# Preserve the verified registry during Passkey recovery

Date: 2026-11-20

## Summary

An independent recovery kit can be used in a fresh browser origin after the vault has moved to
the User service.

## Changes

- Retain the verified registry pin, including its current epoch, after importing a recovery kit.
- Exercise export and import in separate browser stores and verify that recovery can prepare a
  replacement Passkey for the existing vault root.

## Validation

- The regression test reproduced the registry conflict before the fix. The User recovery Worker
  suite and `npm run check` cover the repaired path.
