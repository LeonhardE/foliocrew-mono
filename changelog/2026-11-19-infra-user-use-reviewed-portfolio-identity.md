# Keep User rollout planning within User permissions

Date: 2026-11-19

## Summary

Use the reviewed Portfolio runtime identity in the User rollout input while keeping the User deployment identity scoped to its own service.

## Changes

- Retain the exact Portfolio subject and email checks in the reviewed configuration.
- Verify the live Portfolio service and service account in the separate read-only review before planning and applying.

## Validation

- Exercise the User rollout Terraform mock suite and recheck the production plan with the existing cloud permissions.
