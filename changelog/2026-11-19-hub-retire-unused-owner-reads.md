# Retire two superseded Hub Owner reads

Date: 2026-11-19

## Summary

Task trash and OAuth pending approval use their supported Owner POST queries. Remove the two old GET handlers after checking current consumers and recent production traffic.

## Changes

- Start trash pagination through the existing POST with a null cursor, then continue with the returned cursor.
- Serve pending OAuth approval through the existing POST with its Owner, cookie and Origin binding.

## Validation

- Check first and following trash pages and private 404 responses for both retired GETs.
- Run the Hub service and repository checks.
