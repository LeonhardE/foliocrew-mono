# Verify User recovery evidence in the browser contract

Date: 2026-11-19

## Summary

Add a browser verifier for the existing nonce-bound User recovery evidence.

## Changes

- Verify the exact request digest, local Root pin, active device and archive, validity window, and registry boundary.
- Compare a new response with the previously authenticated version and registry floor before accepting it.

## Validation

- Exercise the shared synthetic evidence in the checked JavaScript bundle and compare its schema definitions with Python.
