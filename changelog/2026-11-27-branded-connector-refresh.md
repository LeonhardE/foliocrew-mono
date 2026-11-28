# Refresh branded connector sessions after discovery metadata is lost

Date: 2026-11-27

## Summary

A connector can renew an existing session on the branded MCP endpoint when its OAuth client has lost the resource metadata it used during setup.

## Changes

- Use the refresh token's single authorized branded resource when the client omits that parameter. Keep the original client, scope, connection, token rotation and revocation checks.
- Record only the fixed rejection category and resource-parameter presence for failed branded token requests.

## Validation

- Exercised the Python MCP SDK through refresh and tool discovery after access expiry.
- Checked origin isolation, transfer, replay, revocation, idle expiry, scope selection and rejection log contents. Ran the repository checks.
