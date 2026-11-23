# Holdings valuation and resource controls

Date: 2026-11-22

## Summary

A newly imported holdings source can show the broker's reported valuation while the workspace obtains market quotes. Resource controls are clearer and dialog close icons are centered.

## Changes

- Request all eligible missing quotes once per pass in serial groups of four. Keep provider limits and show actual quote times.
- Offer distinct broker and market valuations, with two decimal places for displayed prices and unit costs. Include reported signed cash in the headline and keep securities-only weights and returns.
- Accept a name draft during read-only loading. Save names through the existing authenticated and signed flow.
- Distinguish creating a holdings source from adding a security. Label the gain/loss display control.
- Center the close icons using shared geometry for workbench dialogs and the public sample.

## Validation

- Exercise a cold 22-position refresh, serial requests, provider limits, and separate broker arithmetic.
- Check rename entry during resource reads and the existing dialog behavior tests.
- Run `npm run check` from the repository root.
