# Prepare the isolated User database

Date: 2026-11-19

## Summary

Declare the protected named database used by the INF-023 User data handoff.

## Changes

- Add the opt-in Toronto `user-data` database using the existing administrator-owned Firestore module.

## Validation

- Mocked administrator plans verify the database is absent by default and explicitly enabled at the exact resource name and region.
