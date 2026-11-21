# Configure workspace admission for Agent Hub

Date: 2026-11-20

## Summary

Production can require an invitation admission claim on direct user requests to Agent Hub.

## Changes

- Pass the existing authentication setting through this service's managed deployment.
- Leave existing environments unchanged until the operator opts in.

## Validation

- Run the Agent Hub Terraform tests and the repository check.
