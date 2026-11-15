# Prepare Portfolio readers for referenced registry history

Date: 2026-11-15

## Summary

Prepare a compatible reader rollout before enabling lossless deduplication of growing public
registry histories. Existing directory writes and authority verification remain unchanged.

## Changes

- Read legacy arrays, canonical history bytes and the shared versioned certificate-reference
  representation from the existing Portfolio authority field.
- Restore complete independent histories for both SQLite and Firestore individual/batch reads,
  preserving every checkpoint, signature, revocation and generation for normal verification.
- Bound physical JSON to 768 KiB and the entire expanded authority row to 1 MiB; reject corrupt
  references and expansion overflow without writes. Other collections retain their original limits.
- Keep reference writes disabled until compatible readers serve all traffic; document the required
  rollback floor for that subsequent rollout.

## Validation

- Synthetic 25-generation history regression through SQLite and the real Firestore SDK with an
  in-memory RPC boundary, including no-write reads, unchanged legacy writes, corruption, wrong
  roots, invalid signatures and current-time checks.
