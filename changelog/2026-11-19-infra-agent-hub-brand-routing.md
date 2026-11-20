# Manage the Hub configuration for branded entry points

Date: 2026-11-19

## Summary

The existing Agent Hub deployment can recognize its dedicated branded edge
and select the branded Owner handoff when the new workspace is verified.

## Changes

- Accept the dedicated Ed25519 public key through reviewed Hub inputs.
- Keep both workspace origins admitted and order both Owner handoff paths
  with a single explicit choice.
- Preserve the current public link and runtime defaults when inputs are absent.

## Validation

- Check that the optional inputs reject unknown destinations and incorrectly
  encoded keys while preserving the existing default values.
