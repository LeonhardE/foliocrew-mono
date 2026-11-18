# User browser origin admission

Date: 2026-11-18

## Changes

- Allow User to accept one reviewed set of additional exact HTTPS browser origins.
- Keep existing authentication and the canonical Web origin in the deployment.

## Validation

- Mock Terraform plans exercise the legacy deployment, configured aliases and malformed origin rejection.
