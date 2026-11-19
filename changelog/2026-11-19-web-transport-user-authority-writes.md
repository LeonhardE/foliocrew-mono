# Transport signed Owner registry and holdings writes to User

Date: 2026-11-19

## Summary

Extend the scoped Web proxy to carry current registry updates and new holdings
source registrations to the User service.

## Changes

- Validate the exact signed operation, verified owner, vault, and source.
- Bind the returned registry receipt or source incarnation to the original
  submitted payload.
- Keep both requests on the existing authenticated same-origin proxy.

## Validation

- Exercise valid and mismatched mutation receipts in the proxy tests.
- Run repository-wide checks.
