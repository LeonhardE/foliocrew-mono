# Retire the foreground report API

Date: 2026-11-19

## Summary

Remove the seven foreground Owner report routes after the persistent-only task center has shipped.

## Changes

- Remove the foreground report list, counts, detail, revision, evidence, registry, and signed state handlers.
- Keep persistent report query and state validation in the active report routes.
- Keep the production boundary and persistent overview regressions covering unavailable foreground paths and ignored old storage rows.

## Validation

- Verify HTTP 404 and private error caching rules for the retired paths and exercise current and early persistent report history.
