# Validate scoped Owner rollout stages in deployment artifacts

Date: 2026-11-19

## Summary

Allow stage-specific exact owner scopes in the private deployment artifact.

## Changes

- Require the enabled User Owner proxy for either scoped stage.
- Check that the handover and current-read selectors refer to one owner.
- Keep selectors out of the public configuration artifact.

## Validation

- Exercise allowed staged configurations and mismatched owners.
- Run repository-wide checks.
