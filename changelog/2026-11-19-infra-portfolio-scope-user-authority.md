# Scope Portfolio's User authority configuration

Date: 2026-11-19

## Summary

Prepare an exact account setting for Portfolio source reads, revision acknowledgement and invalidations after User takes authority.

## Changes

- Derive the User destination from the reviewed Portfolio audience and preserve the existing trusted Hub identity.
- Leave the ordinary configuration unchanged when no migration Owner is selected.

## Validation

- Test the selected account, fixed destination and missing trust rejection.
