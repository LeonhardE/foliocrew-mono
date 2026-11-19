# Publish committed holdings revisions to User

Date: 2026-11-19

## Summary

Publish exact committed holdings revisions so the current User report authority
can admit them for the selected transferred account.

## Changes

- Require current User authority for selected writes and notify User after the
  Portfolio transaction commits.
- Retry notification from the same committed operation receipt without
  repeating the Portfolio write.
- Bind notification and acknowledgment to the trusted destination, owner,
  vault, incarnation, epoch, and committed revision.

## Validation

- Exercise committed receipt replay and mismatched acknowledgments.
- Run repository-wide checks.
