# Update the explicit native client release to 1.3.1

Date: 2026-11-15

## Summary

The supported standalone native client adopts the shared linear report-link
collector. Existing hosts can explicitly update their reviewed version and pin
while retaining their original private credentials and pending work.

## Changes

- Preserve the complete 1.3.0 manifest, source, build inputs and distributions;
  retain all existing versioned downloads byte-for-byte.
- Build 1.3.1 normally against the reviewed shared core and holdings adapter.
  Keep Node 24.12.0+, the 2MiB asset limit and the fixed public asset allowlist.
- Preserve report policy, full authorization and cryptographic checks. The new
  pin also includes the earlier bounded registry certificate verification memo.
- Require an explicit host version/pin upgrade. Do not silently update installed
  clients, replace keys, renew consent or close existing connections.

## Validation

- Versioned routes, original artifact hashes, manifest integrity and byte limits.
- Real old/new standalone clients reuse pending activation, active profile,
  credential lease and original sealed outbox across an upgrade.
- Genuine signed/PoP/Root/encrypted transactions preserve report receipts,
  current expiry and unsafe-report refusal; maximum newline sections remain valid.
- Existing native client storage, task, input, scheduling and crypto regressions.
