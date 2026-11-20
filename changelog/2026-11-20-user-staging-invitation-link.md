# Isolate staging invitation links

Date: 2026-11-20

## Summary

Staging invitation emails can open the acceptance environment for the same Firebase project.

## Changes

- Label staging mail and validate its destination against the service’s Firebase project before contacting the mail provider.
- Keep the production invitation destination as the default.

## Validation

- Test production mail, staging mail and rejection of unexpected staging origins.
