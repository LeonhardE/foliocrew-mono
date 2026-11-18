# Read current task details in one Hub transaction

Date: 2026-11-17

## Summary

The Hub can return the verified Task Center record, applicable legacy executor evidence and the
current encrypted task packet together when a client opens a task.

## Changes

- Add a bounded Owner detail read with optional current packet and single-connection attribution.
- Reuse the original state, authority, packet and account checks. Resolve legacy evidence only for
  eligible tasks and isolate optional read failures.
- Allow clients to request only what their current view needs.

## Validation

- Compared combined responses with the existing endpoints using synthetic current and legacy tasks.
- Exercised Owner and vault boundaries, unavailable evidence, malformed requests and byte limits.
