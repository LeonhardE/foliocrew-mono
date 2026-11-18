# Managed Workbench edge projection

Date: 2026-11-18

## Summary

The managed Terraform runner can pass an explicitly selected Workbench origin and verification public key to an adopted Web target.

## Changes

- Validate a closed optional Web-only extension against the reviewed deployment fingerprint.
- Require the target's exact consumer marker before projecting the Terraform variable.

## Validation

- Offline tests cover the unchanged existing projections, exact binding, key and origin validation, and the consumer marker.
