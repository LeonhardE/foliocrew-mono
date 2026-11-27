# Remove frozen Hub archive copies after deletion

Date: 2026-11-26

## Summary

A confirmed archive deletion at User can now remove the ciphertext that remained on Hub after authority transferred. The owner can retry this step from another browser session. A repair command covers historical deletions.

## Changes

- Verify a fresh User response and a root-signed deletion for the same owner, vault and transfer. Compare the frozen archive digest and recheck the writer in the removal transaction.
- Preserve the signed transfer used to verify the original public history. Clearing the frozen copy remains safe after a later independent recovery.

## Validation

- Tested actual signed transitions and deletion commands, read-only inventory, wrong vault or receipt, changed writers, replay, an owner with no Hub copy and direct inspection of the stored rows.
