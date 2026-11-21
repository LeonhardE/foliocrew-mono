# Use the registered audience for provider activation

Date: 2026-11-21

## Summary

Agent credentials enrolled through the branded MCP endpoint can be activated in the provider slot after the Owner approves the connection.

## Changes

- Validate the candidate lease against the same server-recorded audience used by credential enrollment. Legacy connections keep their existing audience.
- Exercise branded activation, its stored receipt, and the active provider credential fence in a signed test.

## Validation

- Reproduced the branded rejection on the released code. All 71 focused credential, provider slot, native MCP, and origin tests passed with the fix.
