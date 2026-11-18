# Verify the current vault from the selected task response

Date: 2026-11-17

## Summary

A first task visit can verify its current vault and retrieve the selected task using one read. The separate run-history request can start immediately.

## Changes

- Request the original vault response with full task metadata. The browser applies the same Worker verification, scope checks, current-time checks and source handling as a standalone read.
- Use the original vault endpoint if that section is unavailable. Keep already verified task content fresh only when the response confirms the exact full task metadata in the same private session.

## Validation

- Browser, proxy and controller tests cover negotiated responses, current source data, scope changes, verification failure, partial responses and short revisits.
