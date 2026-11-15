# Align native select chevrons and spacing

Date: 2026-11-14

## Summary

Native dropdowns now share the settings language selector's chevron and right-side inset. The
holdings source chooser, task forms, report filters, Agent duration, currency and FX selectors keep
text clear of the arrow instead of placing the platform arrow against the border.

## Changes

- Reuse the existing 16px settings chevron with a 14px edge inset and 42px reserved text space across
  single-choice native selects. Keep each control's existing background, size, typography and
  native option/keyboard/disabled behavior; listboxes and multiple selection retain platform UI.
- Use the existing dark/light muted theme colors and logical end padding, with a mirrored arrow
  in RTL. Forced-colors mode retains the native platform indicator.
- Remove the settings-only duplicate SVG/spacing so settings and later selects use one style.

## Validation

- Inventory all 19 Web native select sites and statically check shared geometry, both theme colors,
  logical RTL spacing and listbox exclusions. Root records separate CUA visual checks on an isolated
  fixture without using the production account or changing its unlocked session.
- Complete root check and production build verify this frontend-only change. No production browser,
  Owner state, authentication or crypto/Worker implementation is changed.
