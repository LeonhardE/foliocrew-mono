# Explain unavailable immediate task execution

Date: 2026-11-16

## Summary

Task details now explain when immediate execution has not been enabled for the
account, so an unavailable action is not mistaken for another unlock or Agent
plan confirmation requirement.

## Changes

- Show the account availability notice only after capabilities load successfully
  and confirm that task actions are disabled.
- Localize the notice in English, Simplified Chinese and Traditional Chinese.
- Preserve all existing run/delete button guards, permissions and requests.

## Validation

- Render the real task component in all three languages with confirmed disabled,
  enabled, loading and failed capability states; keep both action guards intact.
