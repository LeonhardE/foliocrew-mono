# Bind persistent report writes to a User decision

Date: 2026-11-19

## Summary

Prepare the Hub report writer to use User as the current source authority during cutover.

## Changes

- Authenticate the Agent attempt and return any exact committed receipt before asking User for a new decision.
- Sign the exact attempt, report and manifest fingerprints, and input revisions for the User decision endpoint.
- Hold an allowed decision only within the pending attempt. Keep local task, connection, consent, recipient, request, and Run checks in the report transaction.
- Keep the User report source decision path disabled by default.

## Validation

- Cover both source revocation orderings, expired and mismatched permits, local consent revocation, exact report replay, and fixed-origin delegation.
