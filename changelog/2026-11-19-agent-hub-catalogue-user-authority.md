# Hub discovers resources using current User authority

Date: 2026-11-19

## Summary

Use the transferred account's signed User authority to select eligible Portfolio sources for the Hub catalogue.

## Changes

- Verify the current User proof before and after bounded discovery and recheck the exact Hub transfer marker in each local read.
- Omit disconnected and retiring bindings from the transferred catalogue. Continue to use the producer's exact holdings snapshot metadata.

## Validation

- Exercise transferred listings, an authority outage, a marker change during discovery, and the original catalogue budgets and paths.
