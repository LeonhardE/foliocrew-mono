# Resource discovery reuses pending reads during navigation

Date: 2026-11-22

## Summary

Returning to the resource library while a transferred User vault's separate catalogue request is still loading resumes that automatic read in the current document.

## Changes

- Allow the automatic catalogue request to finish across navigation in a visible, online document with the same account and vault scope.
- Keep background visibility, account changes, explicit refreshes and pending holdings publication on their existing cancellation paths.

## Validation

- Cover rapid navigation during discovery, explicit refresh, pending publication, and late responses across scope changes.
