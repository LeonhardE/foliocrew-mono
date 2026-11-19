# Explain unavailable market charts

Date: 2026-11-19

## Summary

The chart describes an unavailable Yahoo snapshot or a pending refresh accurately. The
request-limit message applies to general admission limits.

## Changes

- Recognize the Market API's known provider and series responses without displaying arbitrary
  HTTP 429 response text.
- Retain displayed cached prices while showing the applicable refresh message.

## Validation

- Run the cache-resource suite for a Yahoo cooldown with a missing chart and an admission limit.
