# Register Firebase Functions source targets

Date: 2026-11-19

## Summary

The backend source registry recognizes build-only Firebase Functions workloads.

## Changes

- Require the Firebase entry point and configuration in addition to runtime dependencies,
  discoverable tests and the isolated image smoke check.
- Keep Firebase Functions workloads outside routine Cloud Run releases and first provision.

## Validation

- Exercise the registry using a synthetic Firebase source directory, including missing files
  and a rejected release-mode promotion.
