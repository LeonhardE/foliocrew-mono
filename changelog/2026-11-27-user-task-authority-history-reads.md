# Faster authority reads for task pages

Date: 2026-11-27

## Summary

Opening task lists and details requires User to authenticate the current vault. Long key histories now require fewer database round trips and repeated signature checks during that read.

## Changes

- Reuse the authenticated starting checkpoint from the same transaction when verifying its successors.
- Load at most twelve history entries per internal batch and share verified certificate signatures within that operation. The public recovery page still returns at most four entries.

## Validation

- The registry regression test reads thirteen signed updates in two batches and checks the returned history and terminal digest. Registry update, recovery page and authority view tests pass.
