# Scope Market runtime access to the new database

Date: 2026-11-19

## Summary

Prepare the existing Market runtime identity to use the protected cache database during INF-022.

## Changes

- Give the runtime its existing Datastore User role on the exact named Market database.
- Preserve the current database binding during the prepared cutover and rollback window.

## Validation

- The Terraform mock plan verifies the exact runtime identity and database scope.
