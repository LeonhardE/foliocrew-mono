# Refresh market data from the workspace

Date: 2026-11-23

## Summary

The Market refresh button uses the signed-in refresh path for the overview and current
security. It shows when data changes and when the provider has no new data.

## Changes

- Keep anonymous market browsing and automatic reads on the existing cache-first path.
- Use the authenticated request for explicit refreshes, preserving visible data while a
  refresh runs and updating relevant watchlist quotes.
- Add user-facing refresh feedback in English, Simplified Chinese, and Traditional Chinese.

## Validation

- Verify the protected request shape, one manual fetch despite a fresh cache, and no-change
  feedback.
- Run `npm run check`.
