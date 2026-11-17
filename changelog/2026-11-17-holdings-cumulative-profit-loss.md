# Cumulative holdings gain and loss

Date: 2026-11-17

## Summary

Saved holdings show cumulative unrealized gain/loss for every position and the selected source.
One percentage/amount control changes both together and defaults to percentage.

## Changes

- Calculate current market value minus recorded cost locally with exact decimal arithmetic.
  Portfolio percentage uses aggregate cost, not an average of position percentages.
- Prefer recorded native book cost, then quantity times average unit cost, with recorded CAD
  book cost as a fallback. Use the existing coherent FX observation and batched transport.
- Keep missing costs, prices and cost FX explicitly unavailable. Incomplete inputs suppress
  the overall return with coverage; zero cost permits an amount but no percentage.
- Add signed gain/loss displays, accessible controls and explanation in English, Simplified
  Chinese and Traditional Chinese. Retain the narrow table's internal scrolling.
- Display and currency switches use existing data without more requests or private uploads.
  No backend, permission, capacity, billing or paid-provider configuration changes.

## Validation

- Holdings valuation arithmetic, coverage, FX fallback, signed rounding and shared-control tests.
- Actual price-hook verification that both display-mode switches make no additional requests.
- Frontend type checking, production build and repository-wide `npm run check`.
