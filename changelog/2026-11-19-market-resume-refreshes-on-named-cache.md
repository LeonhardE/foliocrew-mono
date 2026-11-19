# Resume Market refreshes on the named cache

Date: 2026-11-19

## Summary

Resume the existing upstream refresh and cache-write behavior on `market-cache`.

## Changes

- Remove the temporary cache-only migration flag while retaining the verified named database.

## Validation

- Review the exact saved plan and verify new writes and named-database rollback behavior before retiring the previous grant.
