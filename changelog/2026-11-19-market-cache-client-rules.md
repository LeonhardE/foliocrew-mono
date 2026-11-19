# Deny database clients on the Market cache

Date: 2026-11-19

## Summary

The administrator configuration manages a named Firebase Rules release that denies client access to `market-cache`.

## Changes

- Attach the deny rules to the named Toronto cache database.
- Keep the existing runtime database scope during the initial copy stage.

## Validation

- The Terraform mock plan checks the exact release name, deny rules, and runtime scope.
