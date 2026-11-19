# Read retained Market data from the named database

Date: 2026-11-19

## Summary

Switch the cache-only Market revision to the reconciled named database.

## Changes

- Point the existing Market service at `market-cache` during named-database read verification.

## Validation

- Review the saved plan for the exact database change, then verify retained market data and application health in the named database.
