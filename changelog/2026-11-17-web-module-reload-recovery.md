# Offer explicit page reload after a workspace module failure

Date: 2026-11-17

## Summary

A workspace page that cannot load now offers a user-controlled page reload alongside the existing
in-place retry. This gives users another recovery action when retrying the module cannot succeed.

## Changes

- Add English, Simplified Chinese and Traditional Chinese reload labels and guidance to save
  unfinished edits on other pages; another unlock may be needed after reloading.
- Reload only on an explicit button click. Keep the original module deadline, local retry, session
  handling and Worker compatibility inputs unchanged.
- Document that this entry does not retain older static assets or change already-open documents
  that loaded an earlier version of the failure view.

## Validation

- New component regressions fail on the previous source and pass with this change, covering real
  localized failure rendering, deliberate reload, no automatic navigation and local retry after
  the existing 15-second deadline.
- Focused workspace module, feedback and complete message-catalogue tests, TypeScript checking and
  formatting checks pass.
