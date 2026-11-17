# Keep unavailable task resources visible

Date: 2026-11-17

## Summary

Task editing no longer silently hides holdings when resource discovery returns a valid partial
response with unknown source epochs. Unavailable rows remain visible and disabled, with a local
retry and an explanation that existing selections are retained.

## Changes

- Retain validated resource references for display matching only; unknown epochs never become
  selectable bindings or new grants.
- Keep the editor's original bindings and the existing fresh catalogue, authority and Worker
  checks before saving. Healthy choices remain usable during partial discovery.
- Localize the unavailable state and retry explanation in English, Simplified and Traditional Chinese.
- Leave Agent credentials, authentication, protocols, data sources, runtime and cloud settings unchanged.

## Validation

- Actual parser/component lifecycle regression fails against the original source and passes after
  the fix, covering four unavailable holdings, retained selection, partial reads, explicit retry,
  loading/error guards and independence from Agent credential status.
- All 101 targeted task tests pass with networking denied; Web type checking and changed-file
  formatting pass. Worker hash inputs remain unchanged.
