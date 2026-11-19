# Bind User authority reads to one workload and request

Date: 2026-11-19

## Summary

Define the shared lookup contract for current User registry and Portfolio
source authority after an account transfers.

## Changes

- Bind the verified Owner to one consumer, vault, nonce, minimum epoch, and
  the exact source where applicable.
- Require a distinct signed delegation for this read and preserve the
  existing report decision contract.

## Validation

- Exercise owner, consumer, epoch, source, workload, nonce, and expiry
  mismatches with signed fixtures.
- Run the repository-wide checks.
