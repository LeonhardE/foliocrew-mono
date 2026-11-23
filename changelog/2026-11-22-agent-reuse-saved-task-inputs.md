# Use the current saved resources for each task run

Date: 2026-11-22

## Summary

Scheduled and manual Agent reports can run with the latest authorized, published
resource snapshot even when the source date or coverage is unknown or the last
import falls outside a previous task's maximum fetch age.

## Changes

- Native Agent client 1.3.3 reads and verifies the frozen inputs for each run
  without applying legacy age, timestamp availability, freshness, or coverage gates.
- Retain resource metadata for reports and preserve timestamp integrity, source
  versions, permission checks, and exact retry behavior.
- Preserve the client 1.3.2 release and its integrity pin for existing hosts.

## Validation

- Test an existing task with strict legacy rules using a signed older snapshot.
- Verify that malformed private inputs still block reads and first submission.
- Run the full repository check before publication.
