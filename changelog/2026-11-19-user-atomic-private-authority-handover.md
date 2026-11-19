# Commit the cleaned account's User authority in one transaction

Date: 2026-11-19

## Summary

Verify the signed same-root transition using User's immutable original
baselines and the matching Hub freeze witness before publishing authority.

## Changes

- Check the reviewed account, root, freeze and old source tombstones.
- Commit the new registry start, recovery floor, source index and original
  source acknowledgements together.
- Return the exact first receipt for retries. Refuse a conflicting or
  incomplete handover before publishing a head.

## Validation

- Exercise the same original acknowledgement after cutover, a failed
  receipt write, conflicting witnesses, and the exact signed retry.
- Run the repository-wide checks.
