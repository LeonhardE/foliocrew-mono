# Keep resource reads available as the current registry advances

Date: 2026-11-19

## Summary

The Web resource catalogue and Portfolio view can read a current registry
at sequence 33 and later.

## Changes

- Accept safe positive registry sequences in resource read preconditions.
- Preserve exact current-scope correlation and Portfolio authorization checks.

## Validation

- Exercise a catalogue scope and an existing Portfolio view route at sequence
  33 and reject a mismatched catalogue scope.
