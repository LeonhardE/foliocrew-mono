# Reduce migrated vault unlock requests

Date: 2026-11-19

## Summary

Unlock a renewed archive with one original registry proof when its terminal checkpoint covers the historical certificates.

## Changes

- Verify the terminal bundle against the exact root-signed transition and require it to cover every missing certificate identifier before reusing its owner certificates.
- Use contiguous pages when an older trusted browser checkpoint needs bridging or the terminal proof does not cover the required certificates.

## Validation

- Exercise one-proof Passkey unlock, compatibility with a server that lacks the proof route, and rejection of the wrong terminal bundle.
