# Index owner-scoped Agent Hub report cleanup

Date: 2026-11-18

## Summary

Restore the Firestore queries used to page through an owner's persistent report
and publication records during task cleanup.

## Changes

- Add a collection-scope ascending index on `context.ownerSubject` in each of
  the two persistent report collections queried by cleanup.
- Keep the `context` map exemptions and omit TTL from both overrides.

## Validation

- A read-only production probe reproduced the missing-index error in both
  collections before the change.
- The Agent Hub Terraform plan test checks both overrides, their scope, and
  retention of the parent exemptions.
