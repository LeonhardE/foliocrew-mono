# Reuse verified authority during encrypted task writes

Date: 2026-11-23

## Summary

Task writes with selected resources use fewer calls to User authority when that vault is
managed by User.

## Changes

- Reuse the signed current User proof from preflight within the same task request for
  catalogue discovery. Use the fresh proof from catalogue confirmation for the commit.
- Preserve exact receipt replay, catalogue consistency checks, source scope and the
  final transactional writer fence.

## Validation

- Verify the original catalogue path still reads authority twice and task discovery
  reads it once after the preflight. Confirm an unavailable final proof blocks a write.
- Run the Hub task and catalogue tests and the full repository check.
