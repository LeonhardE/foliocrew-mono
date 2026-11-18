# Foliocrew names for repository checks

Date: 2026-11-18

## Summary

Repository checks use the Foliocrew name for the local backend test image,
security scanner and disposable test directories.

## Changes

- Use the same Foliocrew image tag for local CI jobs and GitHub Actions.
- Use the Foliocrew name in scanner reports, download requests and temporary scan
  and test shard directories.
- Use `FOLIOCREW_GITLEAKS_PATH` in CI. Existing developer overrides using
  `FOLIOVIEW_GITLEAKS_PATH` still select the pinned scanner.

## Validation

- Run repository checks and exercise scanner integration tests with each override.
