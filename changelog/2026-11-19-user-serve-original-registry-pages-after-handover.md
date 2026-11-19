# Serve the signed original registry target after handover

Date: 2026-11-19

## Summary

Let an offline original device fetch the missing signed registry links after the same-Root cutover.

## Changes

- Admit the exact original target named in the verified handover transition alongside the current target.
- Continue using the bounded Owner-only registry page contract. Reject arbitrary historical targets and other accounts.

## Validation

- Test original page readback after atomic handover, altered target rejection, and Owner isolation.
