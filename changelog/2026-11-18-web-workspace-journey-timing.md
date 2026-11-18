# Measure workspace content readiness in the browser

Date: 2026-11-18

## Summary

The Web client records local User Timing measurements for the market overview, task list and
Agent connection list. The measurements include the time until verified content has a paint
opportunity. Login waits, access errors, interrupted navigation and timeouts have distinct outcomes.

## Changes

- Start an interval on document entry or workspace navigation and verify the active view at completion.
- Identify real index quotes and reuse the existing private list readiness signals.
- Expose a bounded browser performance entry with fixed categories for diagnostics.

## Validation

- Tested the timing controller and workspace navigation, including deduplication,
  interrupted navigation, mobile drawer transitions and resumed access.
- Exercised the production Web build locally in Chromium at desktop and mobile sizes with
  controlled market responses. Direct loads, navigation from settings and HTTP 503s produced
  the expected outcomes.
