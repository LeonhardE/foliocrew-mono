# Verify signed workspace admission for private APIs

Date: 2026-11-19

## Summary

Private Firebase account routes can opt in to requiring the workspace admission claim.

## Changes

- Check the admission marker after Firebase verifies the Google identity and token revocation.
- Return an uncached 403 to authenticated users without an admission marker when enabled.
- Preserve the existing default before any consuming service opts in.

## Validation

- Exercise present, missing, altered, spoofed and revoked claims through the shared dependency
  using synthetic credentials.
