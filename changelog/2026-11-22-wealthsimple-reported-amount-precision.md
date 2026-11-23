# Import Wealthsimple amounts with extra decimal places

Date: 2026-11-22

## Summary

Accept broker-reported book costs, quotes, and unrealized returns with extra decimal places. The browser rounds these values to the nearest 12 decimal places using half-even rounding and displays the adjustment in the import review.

## Changes

- Compute per-share cost from the original amount and share quantity before rounding the saved broker fields.
- Keep decimal arithmetic exact through the rounding step and reject amounts outside the existing magnitude limit.
- Keep rounding specific to the broker-reported fields and retain the existing quantity, market value, and cash validation.

## Validation

- Reproduce a 24-place broker value with synthetic CSV data, including ties, negative returns, carry, and the encrypted holdings schema check.
- Run the repository checks.
