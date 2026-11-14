# Record browser Authentication key restrictions and staged rotation

Date: 2026-11-14

## Summary

Document the completed restriction of the deployed public Firebase browser key and the
separate, inactive replacement candidate so operators can preserve current sessions during
an eventual activation and rollback window.

## Changes

- Record the existing key's Identity Toolkit and Secure Token API allowlist and public
  Authentication configuration HTTP 200 checks before and after the restriction.
- Distinguish the created Auth-only candidate from an activated replacement: the production
  trigger/key value is unchanged and the existing key has not been revoked.
- Describe build-time activation, client/session verification and rollback boundaries without
  key material, fingerprints, resource identifiers or new cloud operations.

## Validation

- Matched the recorded restrictions, HTTP statuses, candidate project mapping and unchanged
  trigger/key state against the private operation evidence.
- Complete repository `npm run check` through the signed commit hook.
