# Reuse report state when confirming a read

Date: 2026-11-27

## Summary

Opening an unread report from the task results list now acknowledges it using the version already fetched for display. This removes one full report download from the normal reading flow.

## Changes

- Preserve the fresh task visibility and report integrity checks when opening the body.
- Recheck the report after an explicit state version conflict and preserve concurrent changes from another device.
- Keep the original signed operation for retry if the acknowledgement response is lost.

## Validation

- Exercised title loading, body opening, read acknowledgement, concurrent edits, lost responses and closed reports in the task results hook tests.
