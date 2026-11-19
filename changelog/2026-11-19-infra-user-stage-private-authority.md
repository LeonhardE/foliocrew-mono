# Scope the User private authority deployment

Date: 2026-11-19

## Summary

Use two reviewed User configurations to prepare and activate the selected account's private resources.

## Changes

- Bind both configurations to one Owner and confirm the Portfolio workload against its service and Google identity.
- Enable handover and recovery in preparation. Enable current resource reads, writes, report decisions, and Portfolio integration in the active configuration.
- Preserve the existing closed configuration when the stage is absent.

## Validation

- Exercise preparation, activation and rejected scopes with the Terraform mock provider.
