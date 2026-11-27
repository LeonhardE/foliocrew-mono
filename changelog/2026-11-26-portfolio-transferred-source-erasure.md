# Confirm cleanup at the previous holdings authority

Date: 2026-11-26

## Summary

A permanent deletion of a migrated holdings source now also reaches its previous Hub authority.

## Changes

- Deliver the existing signed mutation scope to Hub after User acknowledges deletion.
- Keep the temporary mutation until both authorities acknowledge the same source and epoch.
  A retry or legacy repair can then complete physical cleanup without a second User request.

## Validation

- Tested a mismatched Hub acknowledgement, interruption, a routing configuration change and
  successful replay with a separate owner's holdings left intact.
