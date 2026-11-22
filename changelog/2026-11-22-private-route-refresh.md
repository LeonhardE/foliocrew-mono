# Preserve the requested workspace page on refresh

Date: 2026-11-22

## Summary

Refreshing a private workspace page now keeps the requested destination visible in navigation
and shows a session check while access is being restored. The market dashboard appears
immediately on public market routes and remains the fallback for visitors without access.

## Changes

- Wait for the account and workspace configuration before choosing the public fallback.
- Keep private panels unmounted and skip market reads on a private route during the check.

## Validation

- Verified direct entry on Settings, Agents, Resources, Tasks and Inbox through session restoration.
- Ran the Web workspace flow, session, navigation timing and authentication regression suites.
