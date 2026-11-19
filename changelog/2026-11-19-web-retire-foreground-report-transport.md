# Remove the foreground report transport from Web

Date: 2026-11-19

## Summary

Close the old report proxy routes and remove the unused foreground Inbox application code.

## Changes

- Remove standalone foreground report routes from the authenticated client and Web forwarder.
- Use persistent report detail, local verification, and signed state updates in the task center.
- Keep local feedback for retired bookmarks and accept the older overview shape during compatible rollback.

## Validation

- Check retired routes stop before forwarding, persistent reports preserve account isolation and update semantics, and Markdown still renders safely.
