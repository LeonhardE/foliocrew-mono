# Store complete Portfolio registry histories by certificate reference

Date: 2026-11-15

## Summary

After the compatible reader rollout, retain growing public authority histories without repeating
identical complete signed certificates in every stored generation. This prepares Portfolio to accept
the full authority synchronized after a new device approval.

## Changes

- Encode complete histories only at the storage boundary in the existing unindexed authority field;
  Firestore uses canonical bytes and SQLite uses the same reference JSON representation.
- Preserve all original bundles, checkpoints, certificate order, signatures and revoked entries for
  the unchanged authority and lifecycle checks. Existing arrays and byte-form histories remain readable.
- Bound the entire expanded authority row to 1 MiB and both physical JSON and exact SDK Document
  encoding to the existing 768 KiB ceiling; reject oversized writes atomically. Other collections
  retain their original limits.
- Require PR300's compatible readers and the request drain window before activation, retain that
  release as the rollback floor, and keep public wire limits unchanged.

## Validation

- Synthetic 25-generation history above the former logical storage limit round-trips through SQLite
  and the real Firestore SDK with an in-memory RPC boundary.
- Ordinary encrypted snapshot writes, Firestore conflict retry, reads and source fencing use that
  complete authority successfully; corrupt, pre-encoded and oversized writes remain rejected.
