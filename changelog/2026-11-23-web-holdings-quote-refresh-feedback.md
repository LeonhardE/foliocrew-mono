# Explain when a holdings price update reaches its limit

Date: 2026-11-23

## Summary

Quota-limited refreshes could return a valid quote batch holding earlier
observations. The workspace now explains the limit even when those prices remain
usable.

## Changes

- Show dedicated daily and temporary quota messages in all supported interface
  languages.
- Stop the same refresh pass after a confirmed quota refusal and retain both
  successful updates and earlier valid prices with their original timestamps.

## Validation

- Test both quota outcomes with mixed new and cached quotes.
- Run the full repository check before publication.
