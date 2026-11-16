# Remove artificial owner request quotas

Date: 2026-11-15

## Summary

Normal task/report navigation and multiple tabs could exhaust the Web proxy's
shared 30-request minute counter, producing local 503s before Hub was contacted.
Remove these application quotas rather than replacing them with higher limits.

## Changes

- Remove the per-UID minute counter, active-slot ceilings and tracked-UID admission
  map from both owner forwarders, including mutation count quotas.
- Retain every Firebase/JWT/UID, origin, route, header, schema, byte, deadline,
  cancellation and fixed-target service-identity check. No new read-POST category.
- Stop emitting the obsolete safe-admission retry marker; upstream failures still
  cannot forge it or turn an unknown write into an automatic retry.
- Leave all cloud capacity, concurrency, billing, IAM, API/resource and budget
  configuration unchanged. Actual requests remain subject to existing usage charges;
  future cost-affecting configuration changes require user approval.

## Validation

- Actual signed owner-proxy regressions replay the incident's sanitized relative
  request timings, 120 reads and concurrent multi-tab loads beyond the former
  per-Owner/global slot limits, without production requests.
- Existing owner authentication, cross-origin, closed request/response, byte-limit,
  timeout, cancellation, identity and unknown-write/error tests remain enabled.
