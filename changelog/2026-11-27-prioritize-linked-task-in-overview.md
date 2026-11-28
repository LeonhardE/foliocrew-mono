# Open a linked task from the initial overview

Date: 2026-11-27

## Summary

Opening a task from its URL can now use the same verified encrypted packet that loads the task
list. On the normal cold-link path this removes a second expensive request for the same task.

## Changes

- Pass the linked task as an optional preference on the existing four-packet overview.
  Check the exact packet order and metadata in the browser and its proxy.
- Share the overview's in-flight request between the list and the link. Keep the existing
  verified User vault and decryption checks for the selected task.
- Read the original task endpoint when the packet is absent, the list is unavailable, or the
  link has waited ten seconds. A late overview can still open the task while the independent task
  read finishes. Older servers receive one compatibility retry within the same owner scope.

## Validation

- Exercised the actual browser request validator and proxy, first-page and out-of-page links,
  known heads, mismatched metadata, an older backend, and an independently delayed list.
- Ran the repository check.
