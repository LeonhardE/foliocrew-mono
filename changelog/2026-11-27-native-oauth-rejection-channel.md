# Make native token renewal failures visible in production

Date: 2026-11-27

## Summary

Operators can identify which native endpoint received a rejected renewal and the OAuth reason code under the production server’s logging configuration.

## Changes

- Send the fixed rejection categories through the server error logger for both verified branded traffic and the primary endpoint. The issuer label comes from the validated routing context.
- Log the issuer category, OAuth error category and resource-parameter presence. Request values remain private.

## Validation

- Exercised both HTTP routes in a fresh process with production Uvicorn logging and the MCP server enabled. Checked the emitted messages and ran the repository checks.
