# Verify a same-Root registry start in User

Date: 2026-11-19

## Summary

User can verify a proposed Owner-signed registry start against the reviewed original vault copy and its staged registry history.

## Changes

- Bind the proof to the same Owner, vault, archive, operation and original registry head.
- Rebuild the verified prior chain from bounded reads and apply the shared transition checker.
- Return the verified start evidence for the future writer handover transaction.

## Validation

- Exercise valid signatures, exact retries, wrong-account requests, wrong archive digests, and missing original evidence.
- Run the repository checks.
