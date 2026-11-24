# Use subdued feedback for quote refreshes

Date: 2026-11-23

## Summary

Existing quotes retain their timestamps when automatic checks cannot acquire newer data.
Explicit holdings refreshes report their result without a blocking error treatment.

## Changes

- Hide internal quote allowances from holdings and suppress redundant Market overview
  notices when cached prices are visible.
- Reuse the holdings valuation for up to an hour. Check again on return or focus when
  the last check is older, while keeping visible prices through the request.

## Validation

- Exercise cache reuse, returning to the page, explicit refresh feedback, and all three locales.
- Run `npm run check`.
