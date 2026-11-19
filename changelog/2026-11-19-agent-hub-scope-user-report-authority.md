# Scope User report authorization to the transferred account

Date: 2026-11-19

## Summary

Select User report source authorization for the configured transferred
account. Keep legacy reads for other accounts and preserve original receipts.

## Changes

- Require the durable account transfer marker for new User decisions.
- Recheck the selected writer in the report commit transaction. A freeze
  that wins the race blocks a late new report on the old writer.
- Keep old receipts available to their authenticated owner during a freeze.

## Validation

- Exercise legacy, frozen and transferred behavior, the transfer race,
  and exact receipt replay.
- Run the repository-wide checks.
