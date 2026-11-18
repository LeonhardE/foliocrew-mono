# Use the Terraform runner's Python in provisioners

Date: 2026-11-18

## Changes

- Prepend the runner interpreter directory to the Terraform process's search path.
- Allow configuration provisioners to find the pinned image's bundled Python while preserving
  saved-plan verification, subprocess input filtering and private diagnostics.

## Validation

- The runner regression test checks Terraform's search path when Cloud Build launches Python
  by absolute path.
