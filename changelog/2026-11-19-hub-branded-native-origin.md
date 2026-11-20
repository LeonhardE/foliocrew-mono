# Route branded Agent requests through the existing Hub

Date: 2026-11-19

## Summary

The Agent Hub can serve the branded OAuth, MCP and signed runtime surface on
the same deployment as the existing native origin.

## Changes

- Require an exact short-lived Ed25519 proof from the branded edge for its
  allowlisted requests.
- Isolate OAuth connections by issuing resource and derive the Owner's
  credential approval audience from the stored connection.
- Run a separate MCP protocol boundary for the branded issuer while keeping
  the legacy origin as the default.

## Validation

- Exercise the actual Hub discovery, MCP challenge and account configuration
  across both origins, including invalid edge proofs.
- Verify same-provider OAuth on both origins, cross-origin token rejection
  and the branded issuer in the Owner setup.
