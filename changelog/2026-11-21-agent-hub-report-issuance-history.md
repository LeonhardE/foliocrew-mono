# Restore saved report titles after vault transfer

Date: 2026-11-21

## Summary

The workbench can verify and open existing reports issued after the vault writer transferred from Agent Hub to User.

## Changes

- Read the exact report issuance checkpoint from the frozen Run history or the verified User registry when the registry advanced before submission.
- Verify the automatic mark-as-read command against the current writer's signed registry after transfer.
- Preserve the stored ciphertext, publication receipt, and browser verification requirements.

## Validation

- Covered saved reports issued at the Run checkpoint and after a registry advance, an expired User authority response, and signed mark-as-read commands after transfer.
