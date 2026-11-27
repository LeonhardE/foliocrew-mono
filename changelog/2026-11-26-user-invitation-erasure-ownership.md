# Follow invitation ownership across email changes

Date: 2026-11-26

## Summary

Account erasure now locates joined invitations and their delivery receipts through the Firebase
owner and Google identity recorded at admission, including invitations to an old address.

## Changes

- Bind the membership and invitation in the same transaction on first admission.
- Retain a different account's joined invitation if it uses the target's current address.
- Stop closure for unclassified historical memberships and support binding the exact surviving
  invitation from an authenticated original Firestore audit commit.

## Validation

- Tested address changes, address reuse, physical readback, missing membership, evidence rejection
  and idempotent repair against the Firestore emulator.
