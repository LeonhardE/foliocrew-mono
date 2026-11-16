# Preserve formatted quote observation timestamps

Date: 2026-11-16

## Summary

The pinned yfinance metadata reader converts an ordinary observation epoch into a
pandas Timestamp. The quote child attempted to serialize that object directly,
exited before emitting the quote and returned `upstream_unavailable` even for valid
synthetic provider metadata.

## Changes

- Normalize only timezone-aware, whole-second datetime observations to UTC epoch
  seconds before the existing JSON boundary. Do not infer a timezone, round a
  fractional timestamp or stringify arbitrary objects.
- Preserve original quote identity, currency, positive price, future/expired time,
  request budget, process deadline and cache validation.
- Leave providers, dependencies, cloud resources, capacity and billing configuration
  unchanged. Normal requests retain their existing usage charges; live source
  availability remains subject to post-deployment verification.

## Validation

- An offline fixture with real pinned yfinance metadata methods/formatter and the
  actual quote subprocess reproduces the original Timestamp serialization exit
  and its `upstream_unavailable` DTO, with network explicitly denied.
- Real-formatter regressions exercise UTC equivalence across timezones and both
  sides of a daylight-saving fold, reject naive/micro/nanosecond observations, and
  retain original future/expired time rejection. Original source fails; fix passes.
