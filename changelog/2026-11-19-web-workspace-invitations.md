# Add workspace invitation settings

Date: 2026-11-19

## Summary

The workspace administrator can manage Gmail invitations in Settings when invitation management is enabled.

## Changes

- Show the User Management section only after User Service confirms the authenticated account's
  invitation capability.
- Add email review, delivery status, retry, revoke, and reissue controls.
- Send invitation requests through a validated same-origin proxy and clear the panel when the
  browser account changes.
- Keep anonymous visitors on Market and disable private navigation and private route content
  when the workspace invitation requirement is enabled.

## Validation

- Verify the invitation proxy, its route and request allowlist, and admin-only response handling.
