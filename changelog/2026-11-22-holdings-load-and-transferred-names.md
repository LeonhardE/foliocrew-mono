# Holdings loading and transferred source names

Date: 2026-11-22

## Summary

Open holdings with fewer redundant requests, use the transferred key history for source names, and separate the display controls from the quote and allocation actions.

## Changes

- Give the first automatic holdings view access to the verified User startup scope. Recheck the current Portfolio view, and take the original authority path when synchronization is required.
- Skip a second quote request when the latest observation is older but the provider's positive cache is still current.
- Verify transferred display names with the existing Owner-signed User registry path for reads, writes, and receipts.
- Use a gain/loss dropdown next to the valuation source and currency selectors.

## Validation

- Exercise a transferred Owner's encrypted rename and receipt.
- Check startup reuse and fallback, stale quote cache age, and the live dropdown path.
- Run `npm run check` from the repository root.
