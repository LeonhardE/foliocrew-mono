# Configure the Web branded Agent link stage

Date: 2026-11-19

## Summary

Manage Web's branded Agent link admission and default separately from its authenticated upstream.

## Changes

- Admit the exact branded endpoint through the existing reviewed Web edge configuration.
- Select the branded copy default only with the explicit preferred stage.

## Validation

- Mock Terraform plans cover admission, the retained upstream and refusal without an enabled Owner Hub.
