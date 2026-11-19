# Exempt the User vault migration baseline from field indexing

Date: 2026-11-19

## Summary

The encrypted archive baseline is loaded by its reviewed document key in the named User database.

## Changes

- Add an indexing exemption for `user_private_vault_baselines.body` in `user-data`.
- Keep its retention policy and database identity unchanged.

## Validation

- Test the exact collection, field, database, and absence of TTL in the bootstrap plan.
- Run the repository checks.
