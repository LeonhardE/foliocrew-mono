# Bound Markdown destination parsing to linear work

Date: 2026-11-15

## Summary

Report validation now collects inline, reference and autolink destinations without
repeatedly scanning long unmatched suffixes. Bounded report text could previously
cause quadratic client or Agent validation work before acceptance or refusal.

## Changes

- Preserve the original capture arrays, ordering, duplicates and angle-link fallback
  using an indexed collector.
- Add one typed pure collector export for bounded trusted composition, retaining
  callers' existing entity, content and URL policy and rejecting non-strings without
  coercion.
- Retain all existing entity, HTML, HTTPS URL, character, section and private-byte
  checks, plus unchanged signature, Root and current-authorization verification.
- Rebuild the checked shared distribution and integrity metadata, including the
  valuation package's frozen-core digest, without rewriting frozen consumer assets.

## Validation

- Generated old/new capture and accept/refuse comparisons, Unicode/multiline and
  maximum-input cases, and genuine signed/encrypted report round trips.
- Local Node timing evidence; no browser, native-host or production performance
  acceptance is inferred from these measurements.
