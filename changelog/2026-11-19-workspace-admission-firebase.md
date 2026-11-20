# Add Firebase workspace admission callbacks

Date: 2026-11-19

## Summary

The Firebase Auth callbacks let User Service check invitations before registration and bind
verified Google identities before returning an application session.

## Changes

- Use Firebase Auth blocking events and forward only the verified account fields needed by User
  Service. The callback uses a short-lived Cloud Run identity with a fixed audience.
- Return an admission claim only following a successful sign-in assessment. Retain a staging
  checklist for rollback, retry and session compatibility.

## Validation

- Run the callback and HTTP boundary tests locally with synthetic account data.
