# Pin the Web private recovery destination in the deployment profile

Date: 2026-11-19

## Summary

The reviewed Web deployment can carry an optional User recovery destination tied to the same numbered User service as the build.

## Changes

- Add an explicit v6 server-only setting with a matched enable flag, exact origin and Firebase project.
- Preserve existing projections if the setting is absent. Keep private routing out of the public flags.

## Validation

- Check legacy projection compatibility and reject partial or foreign destinations.
- Run the repository checks.
