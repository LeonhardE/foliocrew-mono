# Store complete Hub registry histories by lossless references

Date: 2026-11-15

## Summary

Allow ordinary authorized Vault and frozen persistent Run updates to retain complete signed
histories whose expanded JSON exceeds the old physical document ceiling, after compatible
Hub and Portfolio consumers have been deployed.

## Changes

- Encode full certificate JWS values once with ordered per-bundle references and active flags,
  while preserving every original checkpoint, signed byte, logical field and authority check.
- Keep the complete physical JSON and actual Firestore SDK Document within the existing 768 KiB
  limit. Enforce matching expanded Vault/Run/history bounds before encoding or decoding.
- Keep legacy reads without migrations, existing collections/index exemptions, atomic writes,
  CAS/operation receipts, and current public wire limits. Frozen Run copies use the bounded
  expanded-history ceiling instead of applying a physical document limit to the history alone.
- Document reader-floor, Portfolio-consumer and rollback dependencies and the remaining complete
  response growth limit. No user operation, historical pruning or production backfill is added.

## Validation

- Focused SQLite and actual Firestore SDK synthetic RPC tests cover normal Owner updates through
  23/24 signed generations, exact JWS/history preservation, CAS/replay/failed-signature atomicity,
  oversized physical rows, and frozen Run copies above the old ceiling with immutable retries.
- Cross-backend fixtures transfer full logical rows before rewriting, and suffix corruption still
  targets the final original signed certificate without weakening signature/read-count assertions.
- Full root checks and exact-head CI are required before this writer activation is published.
