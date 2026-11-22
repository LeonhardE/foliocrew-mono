# Agent connections for invited workspace members

Date: 2026-11-22

## Summary

Workspace invitees can connect Muse and ChatGPT when the Hub enables invited Agent access.

## Changes

- Require verified workspace admission and an explicit browser approval before a newly eligible account can use its connection.
- Keep the existing pilot connections and account-specific resource and execution authorization.
- Bind invitee eligibility to the approved connection for token exchange, refresh, and signed execution.

## Validation

- Exercise invited and uninvited synthetic Google accounts through the Hub routes with real OAuth exchange and refresh.
- Check the stricter rollout, signed execution and Terraform configuration paths.
