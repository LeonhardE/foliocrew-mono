# Reduce resource catalogue latency for transferred vaults

Date: 2026-11-27

## Summary

Resource discovery checks who controls a transferred vault before and after
calling its data sources. Four extra Firestore round trips on these checks
consumed part of the catalogue request's deadline.

## Changes

- Start each writer-fence transaction with its first document read. A full
  catalogue request now uses eight local Firestore calls for these four checks.
- Keep both signed User authority reads, current fence validation, transaction
  commits, retry handling and the existing request deadline.

## Validation

- A regression test exercises the catalogue service with the Firestore SDK and
  verifies the four live reads, four commits and two external authority requests.
- Ran the catalogue, snapshot and User authority suites and the repository checks.
