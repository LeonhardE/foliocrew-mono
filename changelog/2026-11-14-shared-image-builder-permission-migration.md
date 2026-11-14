# Prepare the shared image builder permission migration

Date: 2026-11-14

## Summary

Manage the existing shared image publisher's narrow build permissions once and provide an explicit,
reversible administrator migration away from its historical project-wide Builder role.

## Changes

- Reuse build-metadata read and Logs Writer; scope Artifact Registry Writer to explicitly selected
  existing image repositories. Add no Storage or source-token access.
- Add explicit adoption, default removal and emergency rollback modes for only the historical
  shared-member Builder tuple. An unmanaged legacy grant requires adoption before removal.
- Preserve per-service deployment/runtime grants, services, triggers, buckets and databases.
- Document exact full-plan boundaries, effective-permission differences, actual build validation
  and rollback without restoring a whole project policy or state.

## Validation

- Provider-mocked foundation checks: 30 passed, including migration modes and preserved deployment grants.
- Complete read-only administrator plans: unchanged baseline; adoption imports only the existing tuple and adds three narrow grants.
- Isolated synthetic full plans: removal deletes only the legacy tuple; explicit rollback restores only that tuple. These are not production saved plans.
- `npm run check` as the mandatory pre-commit gate.
- No remote import, IAM apply or cloud-resource mutation is performed by this source change.
