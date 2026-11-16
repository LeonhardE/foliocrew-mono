# Measure catalogue producer stages without recording private data

Date: 2026-11-16

## Summary

Hub catalogue reads record fixed stage durations to distinguish fresh identity/signing work,
producer I/O and connection setup before choosing a performance change.

## Changes

- Add two bounded request-local timing observations using an independent monotonic clock.
- Observe only six TCP/TLS trace event names; never inspect or retain event details, requests,
  credentials, identities, URLs, headers, bodies or exception values.
- Report missing samples as not observed and invalid observations as unknown. Diagnostic
  failures preserve the original result or exception.
- Keep original authorization, requests, deadlines, retries, response budgets and fallback.
  No connection reuse, feature, cloud capacity or billing change is included.

## Validation

- Offline real HTTPcore TCP/TLS success/failure controls with an in-memory network backend.
- Synthetic owner/delegation proofs, no-error-body reads, observer failure, sample bounds,
  unknown timing and secret-canary controls.
- Observer overhead is measured separately from request or production latency; no production
  request or two-second performance result is claimed.
