# Advance the transferred User registry

Date: 2026-11-19

## Summary

Save same-Root registry advances under the current User writer after handover.

## Changes

- Verify a one-step signed advance against the currently trusted registry.
- Save the immutable registry entry, new live recovery head, and exact receipt
  in one transaction.
- Keep the Owner route disabled by default and bind it to the trusted Web proxy.

## Validation

- Verify checkpoint continuation, exact replay, and stale-version rejection.
- Run repository-wide checks.
