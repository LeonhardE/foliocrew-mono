# Add explicit default-closed Hub task gates

Date: 2026-11-16

## Summary

The Hub infrastructure can now represent the provider-slot and task-center gates
through two separate typed inputs. Publishing this source does not activate them.

## Changes

- Default both flags to false. Slots require personal Agent mode, and task center
  additionally requires explicit slots. Existing prerequisites remain unchanged.
- Add a private full-operator-input guard that binds the approved baseline's raw
  bytes, validates both closed inputs and rejects any change outside the flags.
  Output contains hashes and fixed booleans, never registration or Owner values.
- Document the existing full-input administrator saved-plan route. The inactive
  profile/CI lane, runtime resources, capacity, permissions and billing stay
  unchanged. Actual activation and its usage-cost decision remain separate.

## Validation

- Offline parser, raw-byte binding, dependency, protected-value, legacy-shape and
  actual CLI redaction controls; no cloud or Terraform execution by the guard.
- Mock-provider target checks cover default-off, invalid gate combinations and
  exact unchanged configuration outside the two environment entries.
- No production plan/apply, active-input modification, feature enablement, cloud
  configuration, credential or business request is part of this source change.
