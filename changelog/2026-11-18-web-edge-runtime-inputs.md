# Managed Workbench edge runtime inputs

Date: 2026-11-18

## Summary

An existing Workbench deployment can receive its exact branded HTTPS origin and the edge verification public key through its managed runtime settings.

## Changes

- Add a closed optional input for the origin and canonical Ed25519 public key.
- Keep the existing owner settings and service capacity in the managed Web plan.

## Validation

- Terraform mock plans cover an existing owner configuration, absent edge inputs, an alternate port, and a malformed public key.
