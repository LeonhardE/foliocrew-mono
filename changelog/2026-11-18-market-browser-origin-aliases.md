# Market browser origin admission

Date: 2026-11-18

## Changes

- Give the Market configuration controller an optional exact browser origin list for the branded workspace.
- Preserve the canonical Web origin and existing Market request methods, service identity and runtime controls.

## Validation

- Market mock Terraform plans cover legacy inputs, both allowed origins and rejection of invalid aliases.
