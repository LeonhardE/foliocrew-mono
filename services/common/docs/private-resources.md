# Private resource contracts

FND-018 defines additive wire contracts for the User private resource module. The existing v2
schema, signed representations, full `current` response, and authority verification retain
their byte format and version. The new schemas live in
[private_resources.json](../folioview_shared/encrypted/private_resources.json). The Python
validators use the packaged v2 definitions for base objects. The browser's existing canonical
digest is checked against [the shared vectors](../tests/fixtures/private_resources.json).

## Trust and transaction boundaries

- Owner routes bind the verified Google/Firebase account to the server's opaque owner subject
  and current vault. A caller-supplied owner or vault selector must match the authorized scope.
- Service routes authenticate the workload, exact receiver audience, and permission for the
  operation. Hub may request a report decision for its authenticated connection and frozen run.
  Portfolio retains its narrower source synchronization and read permissions. User's list reads
  and private resource module compose in the same process using the authenticated Owner context.
- Responses carry a closed schema and a versioned profile. Unsupported profiles use
  `unsupported_contract`. Authenticate and authorize before selecting storage. Apply the byte
  bound before parsing, reject duplicate JSON keys, and bind every operation to its verified
  scope. Authority projections carry no decrypted data, bearer credential, or private key.

## Report source decision

Hub constructs `ReportSourceRequest` from its verified frozen Run, the submitted envelope's
verified signing-input fingerprint and operation, and a fresh attempt ID. Include each input's
exact reference, incarnation, source epoch and frozen revision. The manifest fingerprint binds
the rest of the Run. A source-free Run still requires an authenticated owner and vault read.
Use RFC 8785 canonical JSON with SHA-256 for `requestDigest`. Keep the input order from the
attempt for both the producer and verifier.

User reads all requested resources and submits the decision from that same transaction, using
the transaction's current fences and lifecycle. A single ineligible resource denies the batch.
Eligible resources must have the exact incarnation and epoch, and an observed current revision
at least as large as the frozen revision. A known absent resource contributes a `missing`
state. An incomplete or unavailable authority read returns a retryable service error. A
negative decision is scoped to the exact request and carries no expiration or permission.

Hub checks the authenticated User response, digest and 30-second window inside the atomic
local write. A concurrent source revocation that linearizes after an allow preserves that
attempt through its commit. A source revocation that linearizes first denies the next attempt.
The local transaction still checks connection and key status, task authority and consent,
frozen Run lifetime, envelope signature and recipients. Start and input reads use the existing
current-source checks until their producers and consumers switch under separately validated
contracts. A retry of the local write may reuse its unexpired in-memory decision for the same
attempt. A new submission or timed-out User call uses a new attempt and a new decision.

Scope the durable receipt to owner, vault, connection and operation. An authenticated repeat of
the same Run and fingerprint returns the original receipt before asking User for new permission.
Reusing that operation with different content retains the existing conflict response. Keep this
receipt binding and content write in the same Hub transaction. Treat an unavailable or expired
decision as retryable, a denial as insufficient scope, and a mismatched digest as a binding error.
Response authentication comes from the service transport. The response is an internal decision
for one attempt, with no bearer or cross-service delegation semantics.

## Restore and current authority

The browser generates a fresh nonce for each `PrivateRecoveryRequest` and sends it over the
authenticated Owner transport. The User response binds that request, the owner and vault, the
pinned Root, the vault version, the registry epoch/sequence/key epoch and digest, the archive
revision and digest or terminal state, and the lifecycle digest of the source index. The device
result covers the exact requested signing/encryption pair and principal. Use a no-store response
and a maximum 60-second window. The local monotonic floor persists across recovery sessions.
A cold client obtains the current epoch and start from the authenticated authority alongside
trusted Owner identity and Root bootstrapping. A saved archive or signed bundle alone does not
establish the current epoch.

Exact matching evidence can revalidate an already verified local snapshot. Verify a bounded,
continuous page suffix against one fixed current target if a trusted local prefix is available.
For other changes or a missing trusted prefix, complete verification from a trusted start.
Lock protected state while evidence is missing, expired or rejected. Registry verification
does not itself grant access to a holdings source or replace current device/archive checks.

The non-terminal source index is keyed by service, kind and ID and carries the current
incarnation, epoch, and lifecycle state. It supports up to 10 non-terminal holdings entries
and one each of watchlist and channel follows. Its digest sorts by kind, service and ID and
commits the full entries. A deleted incarnation stays in its durable source fence and receipt
store. The current picker takes its eligibility from this index. The cumulative creation limit
on legacy writers stays in place for accounts that still use the legacy format.

## Registry pages and transition

A page carries up to eight original signed bundles and a 256 KiB canonical byte limit.
The decoded HTTP body has the same upper bound. A producer fills the page up to the earlier
limit. Its base is the caller's requested verified cursor and the target stays fixed across
all pages. The browser rejects mixed targets, skipped or repeated steps, a mismatching base or
scope, and corrupted signatures. Validate the exact target digest and key epoch before using
a completed read. Restart on target change or above the client's suffix budget. Persisted
history may index the original signatures by vault, registry epoch and sequence for bounded
retrieval and historical verification.

A new registry start signs `PrivateRegistryTransition` with the same pinned Root using the
existing flattened ES256 control format. It commits the prior head, the new head, the exact
Owner key IDs, archive boundary, current public version increment and operation ID. The
registry epoch, sequence and public version advance. The key epoch stays monotonic. All
retained keys are active Owner certificates under that Root, including a device signing key,
device encryption key and recovery key. The installer compares the previous verified
registry, archive, account, latest lifecycle and exact committed versions in one transaction.
Preserve the original transition receipt for exact replay, record retired key high-water
marks and atomically advance the live head and independently authenticated current epoch
floor. Write the start only after every supported and rollback reader can consume it.

A current-root cold read obtains the authenticated start for the **current** epoch, verifies
the transition and the new bundle, and streams any following pages up to the current head.
A warm reader checks both the durable local floor and the fresh evidence. Serving an older
epoch, including after application rollback or backup restore, cannot restore current write
or Agent authority. Historical verification still uses the original scope and time. Test
the original Owner device/recovery path and legacy write rejection before activating the
new format in an existing account.

## History retention

A durable reference binds the vault, Root, epoch, holder, purpose and required range. Holders
release references only after clearing their own replay or verification requirements. Pin
references for freezes, report verification, receipts, revocations, pending operations,
recovery, offline devices, rollback windows and backup restoration.

The collector reads the complete live references and advances the watermark in a transaction
with the shared reference-generation barrier. Reference creation and release read and update
that same barrier. Commit the reclaim boundary before deleting in bounded batches, and resume
deletion idempotently through the committed watermark. Incoming readers pin before using a
retired segment and reject requests at or below the committed watermark. Exclude the current
epoch and permanent revocation/receipt records from this collector. Include the watermark
and holds in backup and rollback reconciliation.

## Consumer handoff

| Producer                                               | Consumer and compatibility exit                                                                                                                                                                                                                                             |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| RES-001 Authoritative source reads and report decision | HUB-037 consumes after the producer ships. Keep legacy full catalogue checks through the last supported Hub revision using them.                                                                                                                                            |
| RES-001 Owner recovery evidence and registry pages     | WEB-039 and its Worker use opt-in reads. Keep full `current` for full verification and the last legacy Web revision.                                                                                                                                                        |
| RES-001 Source index and source lifecycle              | POR-008, HUB-037 and WEB-039 verify exact current references. Keep the old authority adapter until each consumes the new projection and can roll back safely.                                                                                                               |
| RES-002 Transition, epoch floor and retained history   | User, Hub, Portfolio and Web verify live and historical material. Require compatibility on the production and rollback revisions before writing beyond the legacy limits or starting a new epoch. VAL-015 verifies cutover, original replay and rollback before retirement. |

Record the concrete producer/consumer revisions in the cutover evidence. Keep retired evidence
formats as long as supported history still references them.
