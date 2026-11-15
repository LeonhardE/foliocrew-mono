# Bounded registry-history storage references

Date: 2026-11-15

## Summary

Add a Python shared storage codec that removes repeated complete certificates
while restoring the original registry history for unchanged validation. This
foundation introduces no service consumer or storage migration.

## Changes

- Preserve every complete JWS, checkpoint, generation, entry order, active flag
  and other bundle metadata in a versioned, closed reference representation.
- Reject corrupt, duplicate, unused, out-of-range and non-integer references.
  Check exact expanded size before copying repeated certificates.
- Preserve canonical legacy list/byte reads without writes, keep the 768 KiB
  encoded ceiling, and allow consumers only to tighten the 1 MiB expanded limit.
- Keep all existing Root, signature, schema, authorization, revocation and
  complete-document checks the consuming service's responsibility.

## Validation

- Synthetic 23-to-24-generation histories retain all 575/624 certificate
  occurrences, 47/49 distinct complete JWS values and identical authority results.
- Focused regressions cover canonical bytes, metadata, isolated copies, strict
  references, size limits, expansion bombs, signature pollution, wrong Roots,
  current time, rollback and revocation.
