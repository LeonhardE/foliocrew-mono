# Offline candidates for additional browser origins

Date: 2026-11-18

## Changes

- Accept an explicit deployment profile v6 with per-target HTTPS browser origin aliases.
- Render and verify a candidate bound to one reviewed deployment and its canonical Web origin.
- Require a target's explicit source opt-in before passing additional browser origins to Terraform.
- Keep existing deployable inputs and service identity configuration independent of browser admission.

## Validation

- The infrastructure regression suite exercises old projections, target and instance binding,
  malformed origin rejection, deterministic ordering and private CLI outputs.
