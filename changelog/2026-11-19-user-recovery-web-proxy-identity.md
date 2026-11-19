# Verify the Web workload on private Owner reads

Date: 2026-11-19

## Summary

Bind User's opt-in recovery and fixed-target page reads to the existing Web proxy workload.

## Changes

- Require a Google-signed token for the exact User audience alongside the verified Owner login.
- Return the private response contract with no-store cache behavior.

## Validation

- Synthetic route tests cover missing and untrusted workload credentials, exact Owner scope and the disabled rollout setting.
