# Preserve v3 Owner errors through the private proxy

Date: 2026-11-17

## Summary

Provider connection, task center, and private display name routes now use the
Hub's existing standard error boundary.
A missing operation receipt remains a formal `not_found` response, allowing the
Owner's existing receipt-first authorization flow to continue with its original
signed command instead of stopping at a proxy error.

## Changes

- Include these three existing v3 Owner route families in the closed error response
  framing, including authorization failures, receipt recovery, and unsupported methods.
- Preserve strict frontend response validation, signature checks, idempotency,
  provider slot controls, and all cloud capacity and billing configuration.

## Validation

- Real ASGI and SQLite regression: missing receipt, signed activation, idempotent
  replay, and subsequent receipt lookup.
- Formal error schema checks cover authorization, integrity, transport, disabled
  gates, unsupported methods, and private exception suppression across these routes.
- Actual frontend error forwarding accepts the formal missing receipt and rejects
  the former unframed response in a synthetic offline comparison.
