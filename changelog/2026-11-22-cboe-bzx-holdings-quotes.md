# Cboe BZX holdings quotes

Date: 2026-11-22

## Summary

Holdings listed on Cboe BZX can use public quotes and instrument search.

## Changes

- Recognize the BATS market with the verified Yahoo Finance exchange code BTS. Continue checking the returned instrument, currency, and observation time.

## Validation

- Verify the Cboe BZX adapter and rejection of a different exchange.
- Run `npm run check` from the repository root.
