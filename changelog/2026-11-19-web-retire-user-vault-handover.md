# Retire the one-time Web vault handover

Date: 2026-11-19

## Summary

Remove the completed migration from Settings and the active browser worker and proxy.

## Changes

- Remove the handover actions, signing flow, and handover request forwarding.
- Preserve ordinary unlock and verification of the signed registry start. Accepting a verified User head can still clear a pending local copy left by an older browser release.

## Validation

- Exercise registry recovery, the stored pin upgrade, and rejection of both retired proxy paths.
