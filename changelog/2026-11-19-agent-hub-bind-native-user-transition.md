# Bind new native connections to transferred User authority

Date: 2026-11-19

## Summary

Allow a verified and explicitly selected transferred account to authorize a
new native runtime connection under its signed User transition.

## Changes

- Preserve exact callback replay and separate new connections from former
  OAuth families when confirming the same account.
- Require matching transfer evidence for exchange, access and refresh.
- Keep the feature disabled by default.

## Validation

- Exercise authorization code exchange and refresh for the current transition
  and deny all original credentials and stale callbacks as new authority.
- Run repository-wide checks.
