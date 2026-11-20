# Add Gmail workspace invitation endpoints

Date: 2026-11-19

## Summary

User Service can store, deliver, and redeem workspace invitations for specific Gmail accounts.

## Changes

- Restrict invitation administration to the configured Firebase UID. Return a boolean capability
  from the authenticated settings endpoint.
- Reserve delivery in Firestore, use a bounded provider idempotency window, and bind retry and
  revoke actions to the invitation revision they were issued for.
- Evaluate Google identity admission using a dedicated workload identity. Bind the Firebase UID and
  stable Google subject in the same transaction that accepts the invitation.
- Require deployment configuration before enabling invitation administration or workspace access
  checks. When enabled, the membership check applies to direct User Service requests.

## Validation

- Passed User Service invitation tests covering administration, delivery, retry, revocation,
  expiration, and Google identity binding.
