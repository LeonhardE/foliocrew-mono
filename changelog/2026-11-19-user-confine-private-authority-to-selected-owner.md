# Restrict User private authority to the selected Owner

Date: 2026-11-19

## Summary

Keep the production private-resource migration and current-authority endpoints limited to one selected account.

## Changes

- Recheck the selected Owner after verifying the browser or workload identity and before looking up or changing private state.
- Require a valid exact Owner configuration in the production runtime.

## Validation

- Verify the selected account, an unrelated authenticated account, and missing or invalid production configuration.
