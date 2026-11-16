# Batch current catalogue reads with bounded path hints

Date: 2026-11-15

## Summary

Save one database read round trip when a resource directory's source-fence paths
match the previous successfully verified directory for the same Owner and Store.

## Changes

- Retain only up to ten immutable fence-document keys per Owner, with 64 entries
  and a five-minute lifetime on each Store instance. Do not cache source data,
  Root proofs, time checks or authorization decisions across requests.
- Batch those hints with the fixed current Owner Vault read, rederive all real
  keys after the original complete verification, and supplement changed keys in
  the same transaction. Publish hints only after that transaction succeeds.
- Keep the original final fresh Vault/fence/name snapshot, independent source
  reads, response contracts, budgets and all current authorization checks.

## Validation

- All 65 focused regressions passed, including real Firestore SDK and SQLite
  cold/warm read counts,
  changed refs, owner/Store isolation, expiry, retries, Root/time/fence failures,
  partial batches, bounds, concurrent access, DTO equivalence and zero writes.
- This reduces a proven read phase; it does not establish a two-second UI result.
