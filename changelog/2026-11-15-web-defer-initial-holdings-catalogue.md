# Defer holdings discovery until its workspace scope is known

Date: 2026-11-15

## Summary

The default holdings category requests discovery after its existing verified workspace scope is
available, avoiding directory reads that initialization immediately invalidates.

## Changes

- Reuse the private-name Owner/vault/unlock scope prerequisite without waiting for aliases,
  feature capabilities, Portfolio responses, write eligibility or unrelated workspace activity.
- Keep catalogue demand and cancellation separate from User list reads and channel writes.
  Ineligible catalogue state remains unknown and cannot seed a task.
- Preserve the original receipt timestamp, 30-second reuse, bound publication checks, scope
  invalidation, explicit retry and the existing watchlist/channel and legacy caller behavior.

## Validation

- Actual ResourcesView, ResourceLibrary and hooks cover initialization, disabled or slow name
  capabilities, cancellation, Owner/vault/generation/source-epoch changes, User reads/writes,
  exact and changed snapshots, task selection, explicit retry and the original cache deadline.
- Focused regressions include the existing publication, resource controller and component suites.
  The same added regressions fail against the prior production components.
- Owner runtime hash inputs are unchanged; a production bundle comparison is still required
  before making a deployed runtime compatibility claim.
