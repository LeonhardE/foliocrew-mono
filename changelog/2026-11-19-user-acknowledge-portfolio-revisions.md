# Acknowledge current Portfolio revisions for report authority

Date: 2026-11-19

## Summary

Allow the configured Portfolio workload to acknowledge an already committed
opaque holdings revision for a transferred User vault.

## Changes

- Advance only the matching active source incarnation and epoch.
- Preserve monotonic acknowledgment under retries and concurrent invalidation.
- Keep access under the existing default-off Portfolio workload guard.

## Validation

- Verify that reports can use an acknowledged revision and that delayed
  publication cannot reopen a retired source.
- Run repository-wide checks.
