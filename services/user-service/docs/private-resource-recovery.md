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
