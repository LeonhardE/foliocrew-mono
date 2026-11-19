# Retire the Web proxy for foreground Agent connections

Date: 2026-11-19

## Summary

Agent management uses current persistent and OAuth connections. Remove the old foreground connection readers and revocation rules from the Web transport.

## Changes

- Reject the four former Owner connection routes before token access and before forwarding.
- Remove browser parsers that only processed these historical connection responses.

## Validation

- Run 140 focused checks for the browser requests, Web proxy, connection display and persistent routes.
- Run the repository checks.
