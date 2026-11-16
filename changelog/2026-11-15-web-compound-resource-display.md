# Share verified resource display discovery

Date: 2026-11-15

## Summary

Resource catalogue and private-name automatic reads share the released bounded Hub display read,
reducing an eligible initial three-request sequence to one request.

## Changes

- Bind display expectations to the exact private public-Vault snapshot accepted by the existing
  Worker operation, and publish it atomically on normal unlock and shared resume. Read-only access
  remains eligible; optional derivation failure retains the successful operation and legacy reads.
- Validate the complete DTO and all seven Owner/vault/Root/version/checkpoint/epoch fields before
  extraction. Only the explicit aggregate-size hint falls back to the original independent reads.
- Add a bounded local scope to existing in-flight GET coalescing, preserving the two-read pool,
  subscriber cancellation, original receipts, explicit refresh and write/journal recovery lanes.
- Reuse the original alias DTO validator and its unchanged command/count limits at both boundaries.

## Validation

- Actual AuthProvider, ResourcesView and both hooks verify single-request sharing, closed browser
  and BFF admission, errors/fallback, cancellation, TTL and original explicit fresh-read counts.
- Original Kernel/crypto operations exercise normal/shared unlock, expired read-only access,
  atomic association publication, late Owner changes, mutation isolation, optional failure and
  unaccepted source recovery without extra verification RPCs or storage writes.
- Scope/DTO regressions retain legal 32-generation histories, the original 12288-byte command cap,
  maximum-length encrypted names and exact 1MiB aggregate body boundaries.
- Actual production build preserves ab and both Worker factories/all eight closure paths, byte
  lengths and SHA256 values against the verified production baseline. Deployment globals were
  not executed. This change does not establish a fixed cold-start or complete-page latency.
