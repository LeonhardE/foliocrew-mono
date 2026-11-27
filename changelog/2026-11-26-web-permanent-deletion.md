# Complete permanent removal from the workspace

Date: 2026-11-26

## Summary

Owners can permanently remove a task from the trash, remove a retired invitation, and finish removing a holdings source when its last server receipt has already been erased.

## Changes

- Confirm the selected task and version before issuing permanent deletion. Show a retry for an unconfirmed outcome.
- Match the pending signed holdings removal to the current vault, check the service outcome and clear the old selection and cached content.
- Confirm that the former vault service has cleared its migrated key archive before completing the deletion on this device.
- Offer removal of expired or revoked invitations and verify the requested revision.

## Validation

- Exercise holdings deletion and lost responses, the invitation transport and workspace, permanent task removal, and the owner route for archive cleanup.
