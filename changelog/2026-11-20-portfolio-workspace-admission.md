# Configure workspace admission for Portfolio

Date: 2026-11-20

## Summary

Production can require an invitation admission claim on direct user requests to Portfolio.

## Changes

- Pass the existing authentication setting through this service's managed deployment.
- Leave existing environments unchanged until the operator opts in.

## Validation

- Run the Portfolio Terraform tests and the repository check.
