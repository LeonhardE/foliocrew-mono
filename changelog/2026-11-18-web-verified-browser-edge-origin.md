# Verified browser origin for Workbench ingress

Date: 2026-11-18

## Summary

The Workbench can verify requests delivered from an explicitly configured branded HTTPS edge while keeping its existing owner authentication.

## Changes

- Verify a short-lived Ed25519 proof of browser Origin, upstream Host, method and destination before treating a relayed browser request as same-origin.
- Keep the proof in the Web boundary and retain the existing private response cache policy.

## Validation

- Exercise the existing Hub and Portfolio owner proxy suites and sign a synthetic proof with Web Crypto.
