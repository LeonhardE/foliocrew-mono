# Project reviewed invitation settings into User infrastructure

Date: 2026-11-19

## Summary

Managed User plans can include the invitation Secret Manager version references and the precise
admission workload identity.

## Changes

- Validate the closed User-only extension against the previously reviewed instance digest, the
  existing User audience, and the dedicated numeric callback subject.
- Require the invitation consumer marker before applying the configuration.

## Validation

- Exercise exact projection, source opt-in, preserved inputs, and rejected invalid versions,
  subjects, or target selection with synthetic profiles.
