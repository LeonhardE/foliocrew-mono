# Bound Python report link parsing to linear work

Date: 2026-11-15

## Summary

The shared Python trusted-client report guard no longer repeatedly scans long
unmatched Markdown suffixes. A bounded report section could previously cause
quadratic parsing work before the existing content policy accepted or refused it.

## Changes

- Preserve the three original destination capture lists, order and duplicates
  using an internal indexed collector.
- Preserve Python Unicode whitespace and LF-only multiline anchors, entity
  decoding, raw HTML and attachment rejection, and HTTPS URL validation.
- Retain section, wrapper and cryptographic limits and checks. No backend route,
  permission, frozen client asset or report format changes.

## Validation

- Exhaustive short-input and seeded generated comparisons against the original
  regexes, including Unicode whitespace and different line separators.
- Original content accept/refuse comparisons and maximum-section cases.
- Genuine signed and encrypted report round trip at exactly 65,536 private bytes;
  the original limit still rejects one additional byte.
