# Reduce the cost of loading task lists and opening encrypted tasks

Date: 2026-11-27

## Summary

Display reads for a transferred vault reused little of the verification work from their
current User authority response. Large registries also made Hub reconstruct and validate
the proof from every checkpoint when looking up the one that signed a task.

## Changes

- Compare the stored signed checkpoint first, then its complete ordered certificate list.
  Preserve the existing unique match, original save time, signature, writer and recipient checks.
- Reuse complete, verified User history prefixes within individual task and packet reads.
  Recheck the live writer fence and authority expiry on each transaction attempt.
- Use the existing operation-local certificate verifier across consecutive User checkpoints.
  Each checkpoint, membership change and authorization decision still receives fresh validation.

## Validation

- Compared five local runs before and after the change with 60 signed User checkpoints,
  repeating certificates and four encrypted tasks. Median detail time fell from 349 to 84 ms,
  the four-packet query from 869 to 127 ms and the combined overview from 315 to 130 ms.
  Each response matched the original saved packet. This measures Hub with a synthetic User
  transport and local storage.
- Covered latest and historical task details, batched reads, writer revocation and tampered
  certificates. Reported authorization and client-visible HTTP behavior are unchanged.
