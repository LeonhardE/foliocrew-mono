# Physically remove task and source copies in Agent Hub

Date: 2026-11-26

## Summary

Recoverable task trash has a physical purge path for explicitly purged and expired tasks.
Account administrators can inspect and erase verified accounts in the dedicated Hub database.

## Changes

- Delete proven task versions, run inputs, reports, receipts, stale grants and indexes in resumable batches. Keep one irreversible replay key per purged task until account erasure. Require review for unprovable historical ownership.
- Allow unattended retention maintenance. Deny deleted source authority and remove its encrypted aliases and source content. Preserve independently authored reports and other accounts' records.
- Free source registration slots after confirmed retirement and preserve old signed baselines. After transfer, acknowledge trusted terminal notices after physical cleanup and reconcile historical copies against the Root-signed handover and the exact User receipt.
- Attribute sparse writes at the store boundary and enforce temporary account write holds. Verify inventory, ownership and disabled identity before account erasure and recheck storage before reporting completion.

## Validation

- Exercised signed task and report history deletion through SQLite and the official Firestore emulator.
- Exercised independent owner controls, a concurrent writer during account erasure, quarantine restoration, nested orphan detection and read-back directly from Firestore.
