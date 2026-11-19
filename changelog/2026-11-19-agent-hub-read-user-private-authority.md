# Verify current User authority for the Hub task overview

Date: 2026-11-19

## Summary

Use the transferred account's current User authority for the task overview.
Preserve historical task verification through the original signed evidence.

## Changes

- Match the scoped workload response against the same Root and the exact
  committed registry transition.
- Recheck the durable transfer when reading tasks and reject unstable authority.
- Resolve retained task signatures within their original registry epoch.

## Validation

- Verify the signed continuation and refusal after an invalid transfer marker.
- Run repository-wide checks.
