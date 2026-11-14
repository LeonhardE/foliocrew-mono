# Limit the legacy public configuration scan exception to immutable history

Date: 2026-11-14

## Summary

Prevent a new inline key from escaping required secret scanning by reusing the
old Firebase assignment name in the former bootstrap file.

## Changes

- Require an audited historical commit together with the existing exact path and
  named assignment for both relevant detector exceptions. No key value is added.
- Keep current/index scans and later historical reintroductions subject to normal
  detection, while retaining complete history coverage and public fixture rules.
- Clarify that source scanning and provider-side credential revocation are separate.

## Validation

- Real pinned-scanner fixtures cover known historical input, later reintroduction,
  current source, wrong paths and other assignments in the same historical commit.
- The actual complete history, index and worktree pass the tightened policy.
- Full repository checks are required before commit; no cloud credentials or
  branch-protection rules are changed by this repository-only patch.
