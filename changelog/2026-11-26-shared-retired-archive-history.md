# Verify a transferred archive after ciphertext removal

Date: 2026-11-26

## Summary

Consumers can verify the frozen legacy archive history after permanent deletion of its migrated ciphertext copy. The owner-signed transfer provides the original archive digest and lifecycle version.

## Validation

- Exercise a valid signed transfer, an altered receipt, missing history and a changed transition. Ordinary verification continues to require the original ciphertext or a confirmed deletion.
