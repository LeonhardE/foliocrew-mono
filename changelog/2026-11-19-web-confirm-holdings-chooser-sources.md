# Wait for confirmed holdings sources before showing choices

Date: 2026-11-19

## Summary

Keep deleted holdings options out of the resource picker during a cold reload.

## Changes

- Offer sources only after their exact incarnation is confirmed by the catalogue or the selected source response.
- Show loading and retry feedback for unconfirmed sources. Keep pending deletion recovery accessible without adding that source to the selector.

## Validation

- Cover a cold catalogue delay, a stale response, a replacement incarnation, pending deletion recovery and a verified empty picker.
