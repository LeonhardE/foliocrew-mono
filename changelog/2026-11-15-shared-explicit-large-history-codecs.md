# Explicit larger local registry-history formats

Date: 2026-11-15

## Summary

Add opt-in Python storage-v2, transport-v1 and typed snapshot helpers for complete
bounded registry histories. Existing storage-v1 APIs and all current service,
physical-storage, HTTP and Worker limits retain their behavior.

## Changes

- Keep exact complete JWS table references, original metadata, checkpoints,
  ordering and revocations under the original 32-bundle and 64-entry limits.
- Bound new local history reconstruction to 4,198,400 bytes, with strict optional
  tightening. Keep encoded histories within 768 KiB; full row/response budgets
  remain consumers' responsibility.
- Keep legacy/v1 expansion at 1 MiB even through the new storage reader, and
  explicitly reject storage/legacy representations in the transport decoder.
- Provide a typed local snapshot helper without implying authorization, physical
  fit or a change to generic JSON parsing. No consumer or writer is activated.

## Validation

- Synthetic 28/31/32-generation signed histories roundtrip with identical complete
  authority, including a legal final revocation without increasing 63 entries.
- Regressions cover unchanged v1 behavior, canonical bytes, strict budgets and
  references, independent snapshots, signature pollution, Root/time/rollback and
  revocation. A valid 2,016-distinct-JWS chain still fails the physical limit.
- Original v1 and new-format focused suites pass together.
