# Keep stock search terms out of Market application access logs

Date: 2026-11-18

## Summary

Market stock searches emit a structured application access record with a fixed
route category and HTTP status. Operators can correlate application responses
with the server-generated request ID and response-header latency.

## Changes

- Handle the stock search route and its trailing-slash redirect in both Uvicorn
  HTTP implementations. Search text, client addresses and headers stay out of
  these access records.
- Preserve the status of requests rejected before entering the application and
  keep standard access logging for other routes.

## Validation

- Exercised both HTTP protocols against the Market app with synthetic search,
  validation, redirect, normal access and admission cases.
- Ran the repository's `npm run check`.
