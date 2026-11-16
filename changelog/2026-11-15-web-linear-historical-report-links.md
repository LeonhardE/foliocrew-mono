# Keep historical report validation responsive

Date: 2026-11-15

## Summary

The Web historical report reader now uses the released shared linear destination
collector, removing the same repeated-suffix parsing work from its independent
legacy adapter.

## Changes

- Replace only link destination collection through the existing shared facade.
- Retain the adapter's original entity, HTML, attachment, URL and error policy.
- Keep its 196,608-byte private wrapper, section limits and all historical
  signature, Root, grant, manifest, receipt, recipient and AEAD verification.
- Produce the normal new Worker runtime identity; do not migrate private keys or
  rewrite a previous immutable runtime.

## Validation

- Historical report crypto regressions, including ordinary query ampersands,
  harmless entities, unsafe protocols, cross-owner proof and tampered ciphertext.
- Genuine authenticated opening at exactly 196,608 private bytes, with one more
  byte refused; maximum Unicode sections and original count/length boundaries.
