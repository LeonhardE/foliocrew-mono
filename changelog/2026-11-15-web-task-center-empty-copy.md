# Translate the task center empty list

Date: 2026-11-15

## Summary

The task center's empty list now displays its intended message in English, Simplified Chinese and
Traditional Chinese instead of reporting a missing translation.

## Changes

- Add the missing `taskCenter.noTasks` message in all three supported languages.
- Make the actual task-center component test translator reject missing messages, and cover empty
  lists, unavailable/loading names, saved drafts, original-save notices and unknown-error fallback
  with the real language catalogues.

## Validation

- The same real component tests reproduce the missing message in all three original catalogues.
- Task-center component and catalogue parity/ICU validation tests pass with the completed messages.
