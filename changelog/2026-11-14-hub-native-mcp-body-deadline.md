# Bound native MCP request body reading

Date: 2026-11-14

## Summary

An invalid Agent credential could keep the native MCP boundary waiting for a slow
request body before SDK authentication. Apply a total body-read deadline so incomplete
requests stop without occupying the application until an outer platform deadline.

## Changes

- Enforce a five-second total body-read deadline at the existing `/mcp/v3` boundary.
- Check each chunk against the remaining original byte budget before extending the buffer.
- Keep fixed timeout/overflow errors and no-store headers, stop on disconnect or cancellation,
  and leave SDK authentication, request contracts and processing budgets unchanged.

## Validation

- The native MCP focused suite passes all 12 tests, including actual ASGI/SDK regressions
  for stalled and slow-drip bodies, cancellation, disconnect, pre-allocation overflow,
  exact byte limits and unchanged SDK processing/error-response sending.
- The mandatory complete repository checks run through the signed commit's precommit hook;
  exact pull-request CI must pass before release.
