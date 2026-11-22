# Agent management reuses the verified startup vault read

Date: 2026-11-22

## Summary

Agent management avoids a second full vault download when a transferred User vault just resumed its verified shared unlock.

## Changes

- Consume the recent startup read once during automatic Agent display for the same unlocked session. Explicit refresh and sensitive actions use their existing authority reads.
- Request the current connection summary directly for transferred User vaults. The combined legacy display remains available to vaults it can serve.

## Validation

- Cover the single-use startup handoff, expiry, explicit refresh, and the legacy display path in the Web suites.
