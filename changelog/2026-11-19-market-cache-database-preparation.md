# Prepare a dedicated Market cache database

Date: 2026-11-19

## Summary

The Market administrator root can provision the empty Toronto cache database for INF-022.

## Changes

- Define the protected `market-cache` database through the existing Firestore database module.
- Keep the live service and runtime access on its current database while the protected copy is prepared.

## Validation

- The mock administrator plan verifies the dedicated database boundary and the current runtime scope.
