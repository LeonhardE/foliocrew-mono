# Reduce repeated validation while opening a transferred task list

Date: 2026-11-27

## Summary

A task overview could verify the same User registry once for the authority read and again
for each displayed task. The overview can now reuse the signed historical checkpoints from
that request when verifying each task packet.

## Changes

- Retain historical checkpoints for overview requests that ask for task packets, after the
  complete signed User history and its final head pass validation.
- Bind each lookup to the complete signed history and Root key, Owner, vault, selected
  checkpoint and original save time. Recheck the writer fence in the transaction and verify
  each packet and its writer and recipients. Requests for other endpoints keep the existing
  history handling.

## Validation

- With four synthetic signed tasks at checkpoint 60, the packet read avoided 240 additional
  checkpoint verifications. Median processing time across two runs dropped from 775 ms
  to 162 ms. The four packet responses matched.
- Covered an altered packet, a signed fork, a revoked writer, a save before checkpoint
  issuance and a local writer change during the authority read.
