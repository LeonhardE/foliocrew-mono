# Align watchlist entries in Resources

Date: 2026-11-17

## Summary

The watchlist aligns symbols, company names, instrument types and removal buttons across rows.
On narrow screens, each security’s details sit together to the left of its action.

## Changes

- Reserve shared column widths and allow long names and symbols to wrap.
- Keep the row layout stable when the list is read-only or a removal is pending.

## Validation

- Ran the resource-library interaction tests, including the watchlist pending-action check.
