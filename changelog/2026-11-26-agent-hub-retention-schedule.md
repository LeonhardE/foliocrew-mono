# Schedule expired task removal

Date: 2026-11-26

## Summary

Agent Hub can finish permanent task cleanup in a Cloud Run job while the owner is offline.

## Changes

- A digest-pinned worker processes eligible tasks in the named Agent Hub database. A dedicated scheduler identity can invoke this job through the Google Cloud Run API.
- Provisioning starts with the schedule paused. Enabling the hourly run is a separate rollout step.

## Validation

- Mock-provider Terraform plans cover the empty default, preparation, activation, database-scoped access, the exact target and invalid rollout settings.
