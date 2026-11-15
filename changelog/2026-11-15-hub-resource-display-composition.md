# Combine Owner resource display reads

Date: 2026-11-15

## Summary

Add a backward-compatible Hub read that returns the existing resource catalogue and encrypted
holdings display names together, reducing repeated local database reads for the resources page.

## Changes

- Add Owner-only `GET /api/v3/resources/display` with an explicit closed display scope and the
  original catalogue, display-name capabilities and listing DTOs. All three original GETs remain
  available with unchanged behavior.
- Preserve fresh before/after Root, current-row, source and full fence checks. Read aliases from
  the final bounded database snapshot, including concurrent renames. Keep external User/Portfolio
  discovery outside transactions with the original deadline and producer validation.
- Batch the final Vault/fence/name read into at most 21 documents; retain all existing byte limits,
  custody of encryption material, signature/decryption checks, source failure states and write
  authorization.
- Check original components before the aggregate 1 MiB response; only aggregate overflow selects
  an explicit small separate-mode response. Add no TTL, background work or rollout resource.

## Validation

- Real SQLite and Firestore SDK synthetic regressions cover source counts 0/1/2/10, unchanged
  component DTOs and routes, bounded transactional reads, rename/source/Root/fence races, missing
  and corrupt rows, fresh retry clocks, deadline refusal and explicit aggregate overflow.
- Closed Owner route and real delegated User/Portfolio reader tests cover authentication,
  transport refusals, malformed/oversize upstream responses, unavailable configuration and
  deleted sources. Existing catalogue and display-name regressions remain required.
- These local checks establish behavior and read counts, not production latency or a two-second
  end-to-end acceptance result.
