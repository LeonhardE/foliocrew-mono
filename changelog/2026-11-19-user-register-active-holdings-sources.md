# Register holdings sources under User's transferred authority

Date: 2026-11-19

## Summary

Allow the transferred Owner to register a holdings source using a command
signed against the current User registry floor.

## Changes

- Rebuild and verify the bounded current registry from its signed new start.
- Commit the new source, recovery head and exact receipt together.
- Keep terminal source tombstones and apply capacity to the current index.

## Validation

- Exercise ten retired registrations followed by one new source, original
  receipt retry and rejection of old signed commands.
- Run the repository-wide checks.
