# Keep the device approval fingerprint within narrow screens

Date: 2026-11-14

## Summary

The standalone new-browser approval box now wraps its public root fingerprint on
narrow screens, using the same code styling as the security settings panel.

## Changes

- Apply the existing fingerprint wrapping and typography to review boxes even
  when they appear outside the security settings panel.
- Keep the complete fingerprint, approval labels, explicit confirmation, and
  cancellation behavior unchanged.

## Validation

- Existing new-device approval UI and cryptographic/workspace regressions pass.
- Production build and complete root checks pass.

The separately investigated registration HTTP 413 requires a backend change;
this visual correction does not change registration requests or retry behavior.
