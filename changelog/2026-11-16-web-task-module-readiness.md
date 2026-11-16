# Render task modules through ordinary loading state

Date: 2026-11-16

## Summary

The first Tasks visit loads its code on demand through an effect and renders the resolved component
with current props, avoiding parent Suspense solely for module loading.

## Changes

- Give only Tasks a normal loading-state component; keep the existing loading layout, module
  deadline, error boundary, local retry key and child Suspense protection.
- Share public component code and an in-flight code load without caching mounted Task instances,
  Owner props or business data. Ignore late updates after unmount and clear failed loads for retry.
- Keep all other workspace panels on their original lazy path. No prefetch, extra request,
  business warmup, authentication, Worker, API or cloud configuration change is introduced.

## Validation

- Component lifecycle controls cover success, current props, unmount, shared code, rejected or
  missing exports, the original 15-second timeout, late attempts and in-place retry.
- Real React server rendering confirms the resolved element and genuine child Suspense. These
  tests do not measure browser scheduling or establish a two-second navigation result.
- All 42 targeted module/navigation/session/feedback/task-overview tests pass with networking
  prohibited. Web type checking and changed-file formatting pass, and the 13 Owner Worker hash
  inputs remain byte-identical to the base revision.
