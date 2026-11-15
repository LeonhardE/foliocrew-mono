# Reuse discovery for a matching first holdings snapshot

Date: 2026-11-15

## Summary

Opening the first holdings snapshot can reuse the current resource-catalogue read when both describe
the same source and snapshot. This avoids restarting discovery solely because verified holdings
content becomes visible, while preserving fresh reads for a changed or unconfirmed head.

## Changes

- Bind the published snapshot to the current Auth session/workspace scope, complete source reference
  and source epoch using the already verified metadata/content pair.
- Wait for the same-scope in-flight catalogue or reuse its fresh validated receipt only after an
  exact reference, epoch and snapshot match; retain the original receipt timestamp and read budget.
- Supplement a successful mismatch once, retain explicit stale/error recovery for further mismatch
  or failed reads, and invalidate actual snapshot changes immediately.
- Fence Owner, source, epoch, navigation and read-serial changes. Explicit retry or other legitimate
  refresh supersedes the observer; its own mismatching result remains stale rather than becoming
  usable. Existing legacy version-only callers and write authority checks stay intact.

## Validation

- Actual component/hook regressions cover matched reuse, first import, true snapshot changes,
  full-reference/epoch isolation, superseding reads, stale-action blocking, cancellation and failure.
- Existing resource-library controller, interaction and UI regressions and TypeScript checks pass.
- The change does not establish complete-page latency or assume that the two previously observed
  production catalogue responses described an identical head.
