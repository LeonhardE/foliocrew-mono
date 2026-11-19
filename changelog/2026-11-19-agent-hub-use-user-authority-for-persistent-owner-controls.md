# Bind persistent consent and publication to User authority

Date: 2026-11-19

## Summary

Validate new consent and sealed publications against the selected workspace's current signed User proof and holdings authority.

## Changes

- Read User's current scope outside the Hub commit and recheck the exact transition marker in the commit.
- Require the current User holdings binding as well as exact producer metadata, and preserve exact committed operation replay during an outage.

## Validation

- Exercise current consent and sealed publication, a concurrent source retirement, and exact replay using SQLite.
