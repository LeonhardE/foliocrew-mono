# Restore confirmation of holdings source changes

Date: 2026-11-18

## Summary

The browser can confirm an already accepted holdings deletion, disconnection or
access revocation by using the original operation.

## Changes

- Admit the exact Portfolio synchronization request through the signed-in Web
  client and its same-origin proxy. The request carries only the contract version
  and uses the original operation ID in the route.

## Validation

- Exercise the route through the authenticated browser transport and reject
  invalid operation IDs, extra body fields and unexpected mutation headers.
