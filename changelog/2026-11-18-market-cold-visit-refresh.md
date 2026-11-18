# Complete a cold Market and holdings visit

Date: 2026-11-18

## Summary

The shared provider refresh budget now admits a normal cold Market and holdings
visit within a minute, including stock metrics, quotes, FX and instrument search.

## Changes

- Allow 32 weighted provider units in the existing cross-instance minute window.
- Preserve the daily provider budget, per-key leases and provider cooldowns.

## Validation

- Exercised the normal visit through the Market HTTP routes with a local
  Firestore transport and synthetic provider data.
- Checked the combined visit, cap and subsequent refill in the Market suite.
