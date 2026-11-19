# Support the User source invalidation destination in Portfolio

Date: 2026-11-19

## Summary

Allow one reviewed owner scope to use the User private source invalidation
writer after its handover. Existing Portfolio operations retain their pending
state and receipt checks across the change.

## Changes

- Bind the selected owner's destination to the numbered User origin for the
  same project and region as Hub.
- Send the existing mutation with its original ID and epoch to the fixed
  User path. Timeout leaves the original operation pending for exact retry.
- Keep the existing Hub path for other owners and unconfigured deployments.

## Validation

- Verify scope, destination, audience, a lost response and exact retry.
- Run the repository-wide checks.
