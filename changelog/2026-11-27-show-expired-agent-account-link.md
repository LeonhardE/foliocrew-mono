# Show when an Agent account needs to be reconnected

Date: 2026-11-27

## Summary

Agent management now distinguishes the connection to a provider account from the authorization to execute tasks. When a provider requires a new sign-in, its card shows the account reconnection step and the verified execution authorization's expiry.

## Changes

- Open the existing provider connector from the account reconnection guide.
- On the native confirmation page, show the account confirmation and return steps. Keep execution grants and assigned tasks intact.

## Validation

- Exercised the native confirmation and management entry points, credential expiry boundaries, and existing connection workflows. Ran the repository checks.
