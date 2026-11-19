# Require a scoped User handover for report decisions

Date: 2026-11-19

## Summary

A staged recovery view may support read-only migration verification. Report decisions require the User writer handover reference in the same stored projection.

## Changes

- Check the handover in the same transaction as the source fences and User list versions.
- Keep the handover reference out of Owner recovery responses. Ordinary projection updates preserve the existing handover.

## Validation

- Verify that a complete shadow view cannot authorize a report or promote through the ordinary update.
- Run the repository checks.
