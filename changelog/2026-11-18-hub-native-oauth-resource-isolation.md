# Bind native Agent consent and credential lookup to its issuing resource

Date: 2026-11-18

## Summary

Agent Hub uses the MCP URL recorded when native authorization starts to select its pending consent, authorization code, access token and refresh token. This preserves the existing credentials during preparation for an additional public Agent URL.

## Changes

- Match the stored resource before returning a pending flow or exposing a credential to the OAuth library for exchange, refresh or revocation.
- Use the same resource rule when reading native credentials in an existing transaction. Existing records already carry the resource.

## Validation

- Exercised native OAuth storage isolation and normal consent, exchange and refresh with two configured resources on a shared local database.
