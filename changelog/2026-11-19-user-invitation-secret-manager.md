# Provision User invitation Secret Manager references

Date: 2026-11-19

## Summary

User invitation administration and delivery use pinned Secret Manager versions.

## Changes

- Add opt-in, deletion-protected Secret Manager resources and secret-scoped access for the
  existing User runtime identity.
- Bind the User deployment to numeric versions and the exact workload identity for Firebase
  admission callbacks.
- Keep deployment defaults inactive and keep payloads outside Terraform.

## Validation

- Run synthetic User and bootstrap plans without access to production state or cloud resources.
