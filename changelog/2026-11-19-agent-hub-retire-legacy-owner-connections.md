# Retire the foreground Owner connection routes

Date: 2026-11-19

## Summary

Remove the four retired Owner routes that exposed foreground Agent capability
and connection management. The current persistent connection API continues
to serve existing clients.

## Changes

- Remove the two legacy reads and the two connection and grant revocation
  endpoints from the deployed Hub application.
- Preserve legacy signed material and protocol fixtures for verification.

## Validation

- Verify each retired route returns an uncached 404 without touching legacy
  storage. Exercise current persistent authorization as a positive route
  control.
- Run the repository-wide checks.
