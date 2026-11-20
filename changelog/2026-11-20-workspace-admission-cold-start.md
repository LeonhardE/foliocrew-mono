# Allow for User Service cold starts during Google admission

Date: 2026-11-20

## Summary

Give the Firebase admission callbacks time to reach a User Service instance that has scaled to zero.

## Changes

- Increase the User Service request timeout from 3.25 to 4.75 seconds within the existing six-second callback limit.
- Document the canonical callback URL and the numeric-subject-to-email mapping validated in staging.

## Validation

- In the isolated project, the first User Service health request took 3.79 seconds server-side. The next request took under 0.01 seconds.
- The admission regression test checks the downstream timeout and its room within the callback limit.
