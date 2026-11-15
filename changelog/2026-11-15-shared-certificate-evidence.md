# Reuse immutable certificate evidence during history verification

Date: 2026-11-15

## Summary

Reduce repeated certificate serialization while verifying a complete public key history,
without changing contracts or caching current authorization decisions.

## Changes

- Bind each bundle's certificate checks to a private full Root snapshot and exact JWS strings.
- Retain internally owned immutable certificate payloads, canonical bytes and digests in the
  existing operation-local memo. Unchanged proofs avoid repeated payload comparisons and digest
  serialization; different proofs keep the original canonical comparison.
- Preserve detached public results, bounded success-only storage, per-checkpoint verification and
  every identity, time, role, active/revoked, epoch and historical consistency check.

## Validation

- Existing certificate memo regressions plus focused evidence ownership, re-signing, changed
  payload, separate-operation, no-memo, Root mutation and concurrent-history checks.
- Complete repository checks run through the required pre-commit hook.
- Offline synthetic profiling measures CPU work only; actual page latency requires deployed
  acceptance measurements.
