# Private resource recovery evidence

The User private resource module can read a bounded current recovery head in
one document read. The Owner endpoint is
`POST /api/v3/private-resources/vaults/{vaultId}/recovery-evidence`. It uses the
verified Google/Firebase account and the vault and nonce in the
[shared recovery contract](../../common/docs/private-resources.md). The endpoint
matches the current device signing and encryption pair. Its response expires
within 60 seconds and no later than those keys. It carries the current registry
and archive boundaries and source-index digest, with no archive ciphertext,
certificates, or historical bundles.

## Projection and rollout

The private module stores `user_private_recovery_heads` in the same database as
User resources. SQLite uses a scoped table and Firestore uses one opaque
`view` field per Owner. Exempt that field from indexing on the target
`user-data` database before production use. The installer takes a head produced
from a verified current registry, the current archive boundary, and the
non-terminal source index. Installation checks the previous public version,
same Root and vault, and the monotonic registry and archive boundaries. An exact
repeat leaves the committed head intact.

The route is off by default. `USER_PRIVATE_RECOVERY_READ=true` enables it
for local validation and for the production `user-data` database once the
authoritative writers maintain the projection. Keep it off during data
copying and while an older release can change authority outside this
transaction boundary. Authoritative changes update the projection in the same
transaction. The migrated vault uses the signed User registry start and the
preserved original history for recovery.

Install this reader before enabling removal of terminal source entries on the legacy Hub
writer. Original baselines retain their exact byte representation. A new Hub baseline may
include a non-negative `retiredSourceCount` to reconcile its monotonic vault version with
the remaining source anchors and registry entries. Import fence mutation receipts only for
the exact source incarnations still bound to that vault. Receipts for removed sources stay
on the original Hub for retry handling. User deletion removes the entry from the active
list in the fence transaction and retains the terminal incarnation and idempotency receipt
to prevent reactivation.

The private Owner reads require the original Firebase Owner token and the
Web proxy's Google-signed workload identity. The server checks
`X-FolioView-Proxy-Authorization` against `USER_PRIVATE_OWNER_AUDIENCE` and
the single reviewed subject/email in `USER_PRIVATE_OWNER_WEB_CALLER`. The
audience is the configured User Cloud Run service URL. The application
header preserves the signature for verification. Cloud Run may remove that
signature from its own authorization header.
[Cloud Run service authentication](https://docs.cloud.google.com/run/docs/authenticating/service-to-service)

## Original registry pages

`POST /api/v3/private-resources/vaults/{vaultId}/registry-start/read` verifies
the recorded Owner-signed start and returns it with a fresh nonce for the
authenticated Owner. The migration receipt and original history remain
available to the recovery and verification paths.

`POST /api/v3/private-resources/vaults/{vaultId}/registry-pages/read` serves
original verified bundles for an authenticated Owner under the same activation
boundary. Pin the exact current target from the Owner recovery evidence. A
continuation supplies the exact verified base in that epoch. The initial v1
epoch can start at genesis. An already verified signed start is required to
continue in a later epoch.

The server reads at most four index slots per page, including the supplied base,
and caps the canonical response at 256 KiB. Reads verify the stored bundle scope
with the pinned Root. Clients must still verify continuity from their own
trusted base to the exact target before treating the result as current authority.
A changed target returns a conflict and requires new evidence.

The history collection stores the original bytes keyed by verified Owner, vault,
epoch and sequence. An import stages immutable bundles before publishing the
recovery head. An exact replay leaves the original bytes intact. The head issuer
must verify that the complete required prefix has been staged before publishing
its target. Exempt the opaque `entry` field from indexing on the destination.

## Report source decisions

The internal report decision route verifies the two Hub credentials against the
exact report attempt. In one bounded User transaction it reads the current
account vault, current watchlist and channel metadata pairs, and the exact
holdings fences referenced by the attempt. The response contains only the
private resource contract's decision and its attempt digest.

`USER_REPORT_SOURCE_DECISIONS=true` enables the route. In Cloud Run it also
requires the named `user-data` database. Configure a distinct
`USER_REPORT_DELEGATION_AUDIENCE` ending in
`/internal/v2/private-resources/report-source-decisions`. Enable after the
authenticated holdings authority writer and revocation workflow update the
same fences, and after verifying migration parity and rollback.

## Registry retention inventory

User records a vault-specific retention floor, live registry proof references,
and release tombstones in one atomic record. The same reference ID cannot be
reopened after release. Recording and replaying an identical live reference
are idempotent. A full or unreadable record fails closed.

The maintenance entry point is
`python -m app.private_resources.registry_retention UID VAULT`.
It verifies the original boundary against the signed transfer, counts its
protected history, and prints only aggregate results. With
`--record-reference` it also persists the existing full-range recovery hold.
That hold is reserved for User's original archive and cannot be released
through the ordinary consumer release operation.

This is an inventory entry point. It reports zero deletable entries because
the current archive verifier still needs the original chain and the remaining
writers have not enrolled all their references. It has no deletion mode.

## Permanent erasure

Removing the last watchlist symbol or followed channel removes that item from the current list. A live empty list retains its identity and revision because tasks can reference it and another device can submit a concurrent edit. A verified account erasure removes the containing rows, their revisions and initialization receipts as well.

For full-account requests, confirm both control of the account and the requested scope in the restricted case. Resolve the exact Firebase UID, verified email and Google identity before deleting any identity or lookup record. Pause the subject's workers, in-flight writes, delivery attempts and migration writers across services, revoke sessions and disable the identity. Before deleting the invitation, run the read-only `--delivery-refs` option separately against `user-data` and `(default)` using the verified live UID and email. Direct its private output into the restricted case for mail processor follow-up. It returns the database and matching provider message IDs only. Older or replaced invitations can require a separate provider search. The User operator runs with the case operator's existing Firebase and database permissions. There is no public account purge route.

From the User service environment, supply a JSON object containing the verified `uid` and lowercase `email` through standard input. Keep its values out of shell arguments, unprotected files and logs. Use `python -m app.account_erasure --project PROJECT --database user-data` to inventory and repeat for `--database '(default)'` if the rollout used the older store. Run the same command with `--apply` for the approved databases. It checks the verified disabled account before each batch, uses document-version conditions, repeats the entire scan and prints counts only. A partial failure is retryable while the account remains suspended. Reconcile any historical email addresses known to the case and provider-held delivery records separately. Remove the Firebase identity only after all service jobs and verification have finished.

Indexed lookups include watchlists, FX suppression and preferences, followed channels, membership, the current verified address's invitation, recovery heads, source/name history and authorization receipts. Three legacy formats carry ownership inside packed bytes. The operator pages through those collections in memory, validates their storage keys and retains only the matching references and versions. Inconsistent packed records stop the operation. Use the current User service release for any older database copied into an isolated restore environment. Keep it offline while applying the verified deletion instructions and checking the control account. Use the read-only `--restore-inventory` option with the archived verified `uid`, `email` and `googleSubject` on standard input. This works after the Firebase account is gone and accepts the restored database's actual name. For isolated Firestore tests use a `demo-*` project and loopback emulator. Only promote a restored copy after previously approved requests have been reapplied and fresh inventory reports zero, and unrelated control records remain intact. A successful result concerns the current User database contents; operators must separately track historical read windows, other services, backups and logs before confirming permanent erasure to the requester.

A holdings-source deletion invalidates its eligibility and removes its display alias and all saved rename ciphertext before the User service acknowledges the deletion. Interrupted cleanup resumes on replay of the invalidation request. To repair sources deleted on an older release, use the same operator with `--database user-data --retired-names-only`. Review the count and repeat with `--apply`. This mode authorizes work only on the exact incarnation in an already deleted source fence; it does not require disabling the active account.

Invitation administrators can remove an individually revoked or expired invitation using `DELETE /api/v1/workspace-invitations/{id}/{revision}`. An older revision cannot erase a replacement invitation. Removal is idempotent and the stored invitation disappears from the list. It does not change another membership or recall a previously delivered email.

A migrated vault's cloud-key removal also clears all original wrapped-key copies staged in the User database for that owner, vault and Root. The signed handover and original registry checkpoints authenticate the old digest, and the complete signed lifecycle verifies the deletion and any later independent recovery. The removal endpoint and original-command retry finish interrupted cleanup before reporting a successful deletion. For older removals, run `--retired-archive-only` in `user-data` on the verified account and repeat with `--apply`. This checks for a verified post-handover deletion, including when independent recovery already created a newer archive. Reissuing the old staging operation cannot recreate the original envelope. Hub can obtain the applied deletion command and receipt using the Hub-only archive-retirement lookup. A restored database and any immutable exports still require their separate erasure checks.
