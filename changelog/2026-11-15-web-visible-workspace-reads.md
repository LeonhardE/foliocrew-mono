# Read resource data only while needed

Date: 2026-11-15

## Summary

Resource navigation stops unfinished automatic name reads, and the holdings category no longer
requests the channel-follows list before it is selected. This reduces unused reads competing with
the next page while keeping the existing private-data verification and request limits.

## Changes

- Cancel the automatic display-name read lane on leaving Resources; fence late network, Worker
  and pending-packet results without cancelling explicit renames or their original recovery packets.
- Keep completed same-scope names for the existing 30-second window; vault-version and source-epoch
  changes invalidate the read, and returning without a fresh completed snapshot starts a new read.
- Load channel follows on category selection, retain the existing cache, strict DTO parsing,
  revision-based writes and stale-action restrictions, and distinguish unrequested data from empty.
- Keep ready holdings independent of the unused channel list; category changes cancel only channel
  reads and preserve catalogue reads and explicit channel edits.

## Validation

- Actual hook/component regressions cover delayed capabilities/listings/Worker results, rapid
  leave/return, scope/version/epoch invalidation, unchanged pending packets and in-flight writes.
- Category-demand regressions cover first read, unknown/loading/empty distinctions, 30-second cache
  expiry, failed reads, revision-based edits and Owner changes.
