# Submit transferred key renewals through User

Date: 2026-11-19

## Summary

Send a transferred Owner's signed key renewal and archive rewrap through the selected User authority.

## Changes

- Match the receipt to the exact Owner, vault, nonce, operation and both signed commands.
- Read back the result before the Worker installs local successor keys.
- Send signed cancellation rewraps through the migrated archive writer.

## Validation

- Exercise signed receipt binding and rejection of cross-account or modified replies.
