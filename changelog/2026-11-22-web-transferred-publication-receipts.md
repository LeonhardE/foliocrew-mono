# Resume publication receipts after a vault transfer

Date: 2026-11-22

## Summary

The workbench can resume an already committed Agent publication after the vault registry has moved to User.

## Changes

- Resolve a saved publication's registry sequence through the verified history range. A transferred history can begin beyond sequence one.
- Verify the original receipt and signed ciphertext against the publication-time checkpoint before completing the pending operation.

## Validation

- Reproduced the rejection with a genuine receipt and a registry history that begins beyond sequence one.
- Verified recovery of the original receipt and rejection of tampered ciphertext.
