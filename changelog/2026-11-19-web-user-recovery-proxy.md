# Add the Web proxy for User recovery reads

Date: 2026-11-19

## Summary

Prepare a same-origin path for current recovery evidence and fixed-target registry pages.

## Changes

- Route only the two User recovery queries through the same-origin proxy. Forward the verified Firebase Owner and a dedicated Web workload token to the configured User origin.
- Check Owner and vault scope, the evidence request digest, and the registry page bounds. Return private responses with no-store caching.
- Keep the proxy off unless the deployment explicitly enables it.

## Validation

- Exercise valid evidence and page reads, invalid credential sources, cross-origin requests, and mismatched responses.
