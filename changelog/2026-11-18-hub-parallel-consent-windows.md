# Preserve concurrent native Agent consent windows

Date: 2026-11-18

## Summary

Agent Hub can issue an authorization cookie for the exact pending request so that another authorization tab on the same Hub does not replace its browser binding.

## Changes

- Read the original and request-scoped native cookies while preserving exact origin, cookie uniqueness, authenticated user and pending-request checks.
- Issue the new request-scoped cookie only when `HUB_NATIVE_SCOPED_CONSENT_COOKIES_ENABLED=1`. Roll the compatible reader out to all serving revisions before enabling issuance. Turning the setting off retains read support for outstanding windows. Allow their 30-minute lifetime to pass before reverting to an older binary.

## Validation

- One browser cookie jar completes a pre-existing authorization and two newly opened tabs in an interleaved order, including after disabling scoped issuance.
