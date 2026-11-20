# Persist retired registry references

Date: 2026-11-19

## Summary

User can inventory the original signed registry after authority transfer and
record which evidence must remain available for recovery.

## Changes

- Persist scoped live references and release tombstones alongside the existing retention watermark contract.
- Audit the exact signed original registry boundary and optionally record the archive's full-range hold.
- Report zero eligible entries while the original chain and untracked consumers require retention.

## Validation

- The registry transition tests cover signed archive inventory, owner isolation, exact
  reference replay, and concurrent SQLite registration.
