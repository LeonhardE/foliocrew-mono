# Pause User list writes for final replication

Date: 2026-11-19

## Summary

Prepare the bounded read-only window for the INF-023 list data handoff.

## Changes

- Add the temporary list-write pause flag while the existing User database continues to serve reads.

## Validation

- Check the exact saved User plan and verify the drained source revision before reconciling data.
