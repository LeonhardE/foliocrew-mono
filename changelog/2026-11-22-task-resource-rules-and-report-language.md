# Simplify task resource selection and report options

Date: 2026-11-22

## Summary

Task setup no longer asks owners for data age, coverage, or timestamp rules
when choosing resources for manual or scheduled reports.

## Changes

- Remove resource rules from the setup, review, and legacy edit views in all
  supported interface languages.
- Keep the compatible field required by existing encrypted task readers.
- Add spacing between More options and the report language field.

## Validation

- Task Center and task-controller tests cover the setup, review, and encrypted save flows.
- Run the full repository check before publication.
