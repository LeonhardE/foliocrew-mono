# Retire Market access to the shared database

Date: 2026-11-19

## Summary

Retire the legacy conditional Market runtime grant after the named database handoff.

## Changes

- Remove the administrator-owned Datastore User membership for Market on `(default)`.
- Keep Market's named database, client rules and runtime binding available.

## Validation

- Review the full administrator plan for a single exact IAM deletion after verifying live writes and compatible rollback on the named database.
