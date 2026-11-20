# Stage branded Agent links in Web

Date: 2026-11-19

## Summary

Allow the workbench to admit the planned branded Agent endpoint while keeping the old
copy default until production validation.

## Changes

- Offer an opt-in version of the public Agent link response with the approved origins and copy default.
- Bind native handoffs and credential verification to the admitted origin for each operation.
- Preserve the server-side authenticated proxy and the original DTO for old clients.

## Validation

- Cover version negotiation, exact-origin checks, and branded owner handoff with targeted Web tests.
