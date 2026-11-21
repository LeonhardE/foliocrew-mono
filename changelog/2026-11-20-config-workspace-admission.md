# Configure workspace admission for Config

Date: 2026-11-20

## Summary

Production can require an invitation admission claim on direct user requests to Config.

## Changes

- Pass the existing authentication setting through this service's managed deployment.
- Leave existing environments unchanged until the operator opts in.

## Validation

- Run the Config Terraform tests and the repository check.
