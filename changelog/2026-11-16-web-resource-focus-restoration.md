# Restore saved holdings after returning to the browser

Date: 2026-11-16

## Summary

Returning to a visible Resources page automatically reloads the selected stored holdings instead
of leaving an empty CSV import screen until the owner presses Refresh.

## Changes

- Clear head metadata with hidden-page plaintext and recover the selected source once per existing
  display-cache generation, through the original fresh-vault and Portfolio authority read.
- Keep unknown, saved-but-unread, failed and confirmed-empty states distinct. Unread holdings cannot
  open an empty import or editing flow, and source captions wait for actual content.
- Preserve pending upload and source-mutation recovery, explicit error retry, hidden/inactive
  cancellation, and lock/account/vault fences without changing the Owner Worker or cloud settings.

## Validation

- Real hook/component visibility regressions cover automatic recovery, a formerly empty source
  updated while hidden, duplicate-read prevention, error retry, unknown save acknowledgements,
  unsaved previews, source-mutation journals and late results after lock or account change.
- Resources render/interaction regressions cover unknown/saved/empty/error and new-source states,
  English, Simplified Chinese and Traditional Chinese captions, and import/edit blocking.
- All 150 targeted holdings, Resources, display-cache and feedback tests pass; Web type checking,
  changed-file formatting and whitespace checks pass. The 13 Owner Worker hash inputs remain
  byte-identical to the base revision.
