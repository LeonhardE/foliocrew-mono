# Verify original vault archive history for migration

Date: 2026-11-19

## Summary

Expose the validation for existing Passkey archives, signed lifecycle commands, and original receipts to services that migrate or read the existing vault format.

## Changes

- Verify the original Owner, Root, archive bytes, and accepted lifecycle receipts without changing their wire format.
- Check historical checkpoints against the already verified original registry head.
- Require original signed evidence before treating an absent archive as a deletion.

## Validation

- Verify synthetic archive authorization, revocation, replacement, deletion, and rejection of altered history.
- Compare both verifiers against the scoped production snapshot. The original three lifecycle operations produced the same state and receipts.
- Run `npm run check`.
