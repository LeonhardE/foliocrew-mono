# Additional Agent Hub owner origins

Date: 2026-11-18

## Changes

- Admit reviewed additional origins for owner browser requests.
- Keep the canonical workspace first in the owner list and retain the existing default approval URL.
- Keep the Agent Hub's OAuth issuer and service audience bound to the existing Hub origin.

## Validation

- Mock Terraform plans exercise additive admission, the canonical owner default and protocol origin rejection.
