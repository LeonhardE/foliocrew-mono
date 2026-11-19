# Confirm a vault handover with the original passkey

Date: 2026-11-19

## Summary

Give the verified Owner an explicit review and confirmation for the prepared
User handover, with a retry that keeps the original signed packet.

## Changes

- Review the scoped vault and retained device and recovery keys before signing.
- Stage the same-Root signed operation durably before its first submission.
- Bind the response to the original account, vault, Root, and signing input.

## Validation

- Exercise a lost response and exact signed replay without a second passkey.
- Run repository-wide checks.
