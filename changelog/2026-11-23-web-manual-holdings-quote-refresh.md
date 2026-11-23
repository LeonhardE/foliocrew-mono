# Refresh holdings quotes on demand

Date: 2026-11-23

## Summary

The holdings refresh button requests the latest quotes for supported securities using the
signed-in workspace session. Automatic valuation loads retain their existing budget.

## Changes

- Route explicit clicks through the authenticated Market endpoint and check each supported
  security, including recently cached prices.
- Preserve the current valuation while quotes update. Report new quotes, unchanged quotes,
  pending work, and provider failures in English, Simplified Chinese, and Traditional Chinese.

## Validation

- Exercised the manual and automatic request paths and their feedback with simulated responses.
- Ran `npm run check`.
