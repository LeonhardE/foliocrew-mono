# Count manageable connections in Agent history

Date: 2026-11-17

## Summary

Muse and ChatGPT management cards stop counting old connections once their account link has been
revoked. The history section closes when the final manageable connection is disconnected.

## Changes

- Filter former connections by their account link status when presenting a provider’s history.
- Keep expired credentials with a remaining account link available for management.
- Preserve the underlying connection records and attribution of previously returned reports.

## Validation

- Ran provider grouping and Agent management UI tests for current, historical and revoked connections.
