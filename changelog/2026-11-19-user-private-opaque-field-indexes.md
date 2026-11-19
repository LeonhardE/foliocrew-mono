# Exempt opaque User recovery fields from indexing

Date: 2026-11-19

## Summary

Prepare the existing recovery projection and registry page formats for storage in `user-data`.

## Changes

- Exempt the opaque recovery view and registry entry fields used in document-ID reads.
- Preserve all document retention and other field indexes.

## Validation

- Administrator tests check the exact database, collection and field pairs and the absence of TTL policies.
