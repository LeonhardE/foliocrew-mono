# Read persistent reports in the task center

Date: 2026-11-19

## Summary

Prepare the Web task center for retirement of the foreground report service.

## Changes

- Use the persistent feed for task lists, paging and unread counts while accepting both overview response shapes during rollout.
- Show a local status for an old foreground bookmark without requesting it from Hub.

## Validation

- Web regressions cover both overview shapes, local retired links, persistent report access and read receipts.
