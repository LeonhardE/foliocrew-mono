# Reuse original archive validation in Hub

Date: 2026-11-19

## Summary

Hub reads and applies the original vault archive lifecycle using the shared validation used by the User migration.

## Changes

- Share archive, authorization, withdrawal, and receipt validation across the existing Hub vault and key-renewal paths.
- Keep legacy operation formats, storage and response behavior during the migration.

## Validation

- Run 116 focused archive, vault lifecycle, withdrawal, renewal, and transport tests.
- Run the repository checks.
