# Scope the Web vault handover and current User reads

Date: 2026-11-19

## Summary

Allow separately staged Owner confirmation and current User reads on the
existing Web service.

## Changes

- Require the paired User configuration and a valid exact owner scope.
- Require matching scope when both stages are set.
- Preserve existing Web access and release boundaries.

## Validation

- Exercise the scoped positive and mismatched-owner Terraform plans.
- Run repository-wide checks.
