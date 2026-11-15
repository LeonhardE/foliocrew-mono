# Avoid repeated packaged valuation meta-schema checks

Date: 2026-11-15

## Summary

Reduce the Python valuation definition loader's per-process initialization work while keeping
its schema bytes, public references, input validation and browser distribution unchanged.

## Changes

- Check the packaged valuation schema's exact raw SHA256 before parsing, following the existing
  encrypted schema loader pattern. Full meta-schema validation remains an independent mandatory
  common test against both the source resource and the isolated installed package resource.
- Keep all runtime input size, schema, custom format and semantic checks, detached copies and
  existing errors. Refuse altered or unreadable definitions before parsing or validator creation.
- Document the definition update procedure and the limits of local startup measurements.

## Validation

- Focused packaged-integrity and valuation contract regressions cover tampered definitions,
  whitespace, truncation, an incorrect pin, resource failure, every public root reference,
  installed bytes, detached inputs, custom dates/timestamps and unchanged response budgets.
- Fresh-process offline comparisons use identical local Python/dependencies and network guards.
  They measure a small initialization saving, not production cold-start or two-second UI readiness.
