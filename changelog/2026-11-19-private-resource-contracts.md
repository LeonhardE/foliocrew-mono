# Define private resource authority contracts

Date: 2026-11-19

## Summary

Defines versioned shared contracts for User private resource authorization, Owner recovery, and bounded registry history.

## Changes

- Bind each report source decision to its exact submission attempt and verified inputs, including source incarnations, epochs and revisions.
- Define fresh Owner recovery evidence, registry page continuity and a same-Root registry start with monotonic versions and Owner certificates.
- Define non-terminal source index digests, durable history pins and collection watermarks. Keep the existing v2 full response and signatures compatible.

## Validation

- Shared tests cover cross-scope and stale decisions, both revocation orderings, replaced source incarnations, fresh recovery evidence, 33 checkpoints across pages, same-Root transition, and retention bounds.
- The fixed canonical digests match in Python and the existing browser contract implementation.
