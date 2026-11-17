# Update the Web framework security patch

Date: 2026-11-17

## Summary

Upgrade Next.js from 16.4.2 to 16.4.5, the first patched version for
GHSA-mfr8-8qww-v76h / CVE-2026-119790. The affected version was installed;
the published triggering cache pattern was not found in the application.

## Changes

- Raise the Web dependency floor and lock only Next.js and its matching environment
  and SWC packages to 16.4.5. Preserve every unrelated dependency record.
- Keep authentication, private response validation, encryption, and cloud capacity
  and billing configuration unchanged.
- Let the normal lock-derived Owner runtime version change. Existing unlocked
  sessions are not migrated or refreshed by this change; the new runtime follows
  the existing normal unlock and validation flow.

## Validation

- Exact installed versions, package integrity, and the minimal lock delta were checked.
- All 91 focused Web regressions and type checking passed.
- A production-mode build passed. Its genuine new Owner version matches the normal
  source hash; both Worker factories and all eight closure assets were measured.
