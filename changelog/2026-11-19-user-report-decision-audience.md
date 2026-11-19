# Pin the User report decision audience

Date: 2026-11-19

## Summary

Configure the exact User audience for Hub report decision delegations.

## Changes

- Derive the report path from the configured User origin while retaining its existing catalogue audience and Hub caller.
- Keep the private report decision endpoint behind its own activation gate.

## Validation

- A mock User plan checks the exact report path and keeps prior deployments without Hub trust closed.
