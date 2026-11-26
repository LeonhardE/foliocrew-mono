# Copy the public Client ID for Muse

Date: 2026-11-26

## Summary

The Foliocrew connection dialog lets users copy the public Client ID when
the Muse custom connector setup asks for it.

## Changes

- Show the separate copy action for branded Muse OAuth setup in English,
  Simplified Chinese, and Traditional Chinese.
- Keep the official Muse link, setup message, and authorization sequence.

## Validation

- Verify the clipboard value, localized guidance, and scoped visibility
  in the Agent Management interaction tests.
- Run the repository checks with `npm run check`.
