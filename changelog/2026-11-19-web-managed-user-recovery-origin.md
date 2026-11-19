# Consume the reviewed User recovery destination in Web

Date: 2026-11-19

## Summary

The managed Web service accepts the optional User recovery destination from its reviewed deployment projection.

## Changes

- Pass the User enable flag and matching numbered User origin together.
- Check the Firebase project, region and other enabled service origins before preparing a Web configuration change.

## Validation

- Verify paired input, project mismatch rejection and existing Owner environment compatibility in Terraform mocks.
- Run the repository checks.
