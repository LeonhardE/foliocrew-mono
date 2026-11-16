# Restore holdings price loading and default currency selection

Date: 2026-11-16

## Summary

Saved holdings could show no prices because the browser rejected the loader's native
fetch invocation before sending a request. Returning to a cached source could also
leave a temporary currency selected after choosing the default currency.

## Changes

- Call the supplied fetch function without attaching the loader options as its
  receiver; retain the existing quote/FX requests, parsing, deadlines and cancellation.
- Publish an explicit default-currency selection when resetting a restored view,
  so React updates the selector and removes the reset action immediately.
- Keep cloud capacity, billing configuration, provider budgets and Worker runtime
  inputs unchanged. Actual requests remain subject to existing usage charges.

## Validation

- A local data-URL fixture in a real browser reproduced `Illegal invocation` for
  the original method call; bare, wrapped and detached calls succeeded.
- A strict-receiver loader regression covers cache reads and quote/FX refreshes
  for synthetic manual holdings; the original source fails and the fix passes.
- An actual component/hook regression restores a cached temporary currency,
  switches sources and resets immediately without additional requests; the
  original reset fails and the fix passes.
