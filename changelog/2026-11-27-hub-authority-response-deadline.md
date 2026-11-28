# Let a cold User service respond within the existing authority deadline

Date: 2026-11-27

## Summary

A transferred task or Agent session could fail while its User authority request still had
time to complete. The previous four-second HTTP read timeout also let successive reads
extend beyond a shorter overall deadline.

## Changes

- Give response headers and body the remaining part of the original eight-second lookup
  budget or the caller's earlier deadline. Cap establishing a connection, writing the request
  and waiting for a connection at four seconds each.
- Cancel the transfer at its overall deadline. Log the failed stage and timing using fixed
  categories and durations.

## Validation

- On a loopback HTTP connection, headers delayed for 4.25 seconds produced a verified
  response in 4.28 seconds. The previous implementation failed after 4.01 seconds.
- A delayed body with a 500 ms caller deadline was cut off after 503 ms. The previous
  implementation returned after 699 ms.
- Ran the focused authority, catalogue and snapshot tests and the repository checks.
