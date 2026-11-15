# Encrypted workspace contract v2.0

`folioview_shared.encrypted` is the shared, stateless contract for encrypted
resources, tasks and result revisions. It contains schemas, public verification,
trusted client crypto primitives, authority validation and message budgets. It
does not start a service, resolve arbitrary keys, store secrets, call a model or
provision infrastructure. Existing HTTP/auth helpers and consumers are unchanged.

The opt-in [persistent Agent identity extension](docs/persistent-authority.md#identity-and-session-recovery) separates
an explicitly approved public identity from short-lived session recovery proofs.
It has its own packaged schemas and verifier entry points; it does not change
the P1 grants below, issue credentials or activate a persistent Muse runtime.

The separate [persistent resource consent extension](docs/persistent-authority.md#logical-resource-consent) defines
incremental logical-resource approval, current-and-future version policy and
per-resource revocation. It is an additional current-policy gate, not a legacy
P1 grant or permission to execute a task. Services and clients adopt it separately.

The [independent executor trust extension](docs/persistent-authority.md#independent-executor-trust)
is retired with its Policy/TEE consumers. Its separate verifiers and distribution
are removed. Current personal Agents use the [90-day credential profile](docs/agent-credentials.md)
with existing signed identity/content/consent formats. Historical Owner reads and
original revocation/receipt verification retain their supported contracts.

## Wire format and versions

The exact version is `folioview.agent-workspace.v2.0`, profile `P1`:

- General JSON JWE: `ECDH-ES+A256KW`, `A256GCM`, one fresh library-generated CEK/IV
  per encryption, a separately wrapped key per recipient, no compression.
- The external JWE AAD is the base64url encoding of the UTF-8 RFC 8785 JCS public
  context. Strings are not Unicode-normalized. Financial decimals remain strings.
- A flattened ES256 JWS signs the canonical `{context, jwe}` message. The protected
  header includes the author RFC 7638 P-256 thumbprint, `fv-object+jws` type and
  JSON content type. Controls use the distinct `fv-control+jws` type.
- The carrier has only `contractVersion` and `signedObject`. All public objects
  are closed schemas. No private JWK, arbitrary key URL, optional algorithm,
  private title/summary or plaintext digest is accepted as routing metadata.

`schemas.json` is packaged with the wheel. `schema.load_schema(name)` returns an
independent Draft 2020-12 document with local references. Other languages can
consume it without importing Python. Validation includes UTC timestamps, IANA
timezones and the contract's HTTPS URL restrictions; consumers must implement
the same format checks, beyond a JSON Schema engine's optional defaults.

The Python loader checks the exact packaged `schemas.json` bytes against the
fixed SHA256 in `schema.py` before parsing or creating a validator. Complete
Draft 2020-12 meta-schema validation runs independently in the mandatory common
suite, including an isolated installed-package resource check. Runtime input
size, strict JSON, schema/format validation and detached-copy checks remain
unchanged. This pin is separate from the browser distribution's integrity manifest.

For an approved schema change, first validate the candidate definition directly
with `Draft202012Validator.check_schema`. Compute SHA256 over its raw bytes and
update `_PACKAGED_SCHEMA_SHA256` explicitly in the same reviewed change; even
whitespace changes affect the pin. Rebuild/reinstall the package used by the
development test environment, then run the complete common and contract suites.
The integrity tests must retain their independent full meta-schema check rather
than substituting the runtime loader for it. No schema bytes change as part of
the loader optimization itself.

The frozen v1 and v2-candidate documents are historical inputs, not accepted
versions or aliases. Versioned consumers must require the exact header and body
version, use distinct v2 routes/storage, and reject downgrade or plaintext
fallback. This package does not change any existing route or migrate data.
Migration requires an unlocked trusted client to read old content and create a
fresh v2 object after explicit consent; it does not make historical plaintext
confidential. Rollback must not route v2 ciphertext to a v1 plaintext writer.

Two explicit stable-version refinements are included: operation IDs are 22–128
URL-safe characters (`jsonutil.new_operation_id()` generates 128 random bits),
and a manifest task-envelope reference is a closed descriptor rather than an
untyped object. The existing frozen inputs are not rewritten to hide changes.

## APIs and trust boundaries

| Module                          | Responsibility                                                                                                                                              |
| ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `schema`                        | Detached validation of closed wire DTOs; schemas alone do not authenticate data.                                                                            |
| `authority`                     | Root-signed key directory/checkpoint chain, role/partition/local key epochs, limited device grants, agent Begin intents and fixed control intents.          |
| `envelope`                      | Current-write signatures, trusted owner/object/task/run/recipient bindings, delivery/business revisions, stable operation identities and original receipts. |
| `manifests`                     | Immutable Run/manifest/Begin binding, ordered component pages and separately selected retained author proofs.                                               |
| `crypto`                        | Mature JOSE operations for public verification and trusted client encryption/decryption. No bespoke KDF, key wrap or AEAD implementation.                   |
| `reference_history`             | Lossless, bounded internal storage references for repeated complete registry certificates; decoded bundles remain untrusted.                                |
| `reference_history_v2`          | Explicit opt-in storage-v2, transport-v1 and local history snapshots; existing storage-v1 and wire budgets remain unchanged.                                |
| `private`                       | Trusted decrypting endpoint's typed payload and exact private/public identity checks. Not a Markdown renderer.                                              |
| `jsonutil`, `budgets`, `errors` | Bounded strict JSON, JCS, base64url, whole-message limits and fixed diagnostics.                                                                            |

The owner root key must be pinned through an independently trusted enrollment
path. `verify_registry` takes that key and the prior verified checkpoint. It
rejects known rollback, changed history, forgotten revocations and ambiguous key
generations. First enrollment without a prior checkpoint cannot independently
detect a server presenting an older, otherwise valid directory. Consumers must
persist their last checkpoint/root pin; a server key URL is not a substitute.

When verifying consecutive history bundles in one operation, callers may create
one `authority.RegistryCertificateMemo` and pass it as
`verify_registry(..., signature_memo=memo)`. Successful static certificate signature,
closed schema and complete public P-256 key/thumbprint checks share one entry,
keyed by the exact Root public key, type, expected key ID and complete signed bytes.
Each bundle uses one private Root snapshot for its checkpoint and certificates.
Certificate lookups bind that complete Root context to the exact three immutable
JWS strings, without serializing the same Root and JWS again on each static hit.
Verification uses the same private inputs, including when another thread changes
the original dictionaries during crypto. Successful evidence owns its frozen
certificate payload, canonical bytes and digest. Consecutive registries may share
that private immutable value, so only identical internal proof identity can skip
repeated prior-payload serialization; other values retain the full comparison.
Public `cert()`, `_verify` and `_certificate` results remain detached copies.
At most 128 entries and 1 MiB of encoded keys, payloads, canonical bytes and static
metadata are retained; beyond either
limit full validation continues without adding evidence. Concurrent successes cannot
exceed either bound. Pending work and failed static validation are not retained.
Every checkpoint signature/schema and every entry's identity, role/capabilities,
issuer/key ID, active/revoked flag, epochs and prior-history relationships still run.
Certificate selection always checks current time and authorization. Discard the
memo after the operation; do not retain it across requests or use it to cache a
current registry, permission or revocation decision. No second payload-canonical
key is constructed for a static hit.

`reference_history.encode_reference_history(history)` returns an internal storage
object with exactly `format`, `certificates` and `bundles`. The version is
`folioview.reference-history.storage.v1`. The certificate table retains every
distinct complete `protected`/`payload`/`signature` tuple; it never identifies a
certificate by its payload or key ID alone. Each bundle wrapper contains exactly
`bundle` (the original metadata except `entries`) and `entries` (ordered
`[certificateIndex, active]` pairs). Checkpoints, contract versions, all metadata,
generation and entry order, active flags and signed bytes roundtrip unchanged.
First-use indices must be consecutive from zero; duplicate or unused table
certificates, invalid/non-integer/boolean references and unknown formats fail
closed. A template cannot override its referenced entries.

`decode_reference_history(value)` accepts that storage object, an existing legacy
history list, or canonical JSON bytes for either representation. It returns an
independent list with an independent certificate object at every occurrence.
Legacy reads do not migrate or write anything. Stored bytes must be strict,
canonical JSON within the existing 768 KiB ceiling. Encoded reference objects
also remain within 768 KiB. Expanded history defaults to at most 1 MiB, with at
most 32 bundles, 64 entries per bundle, 2,048 references/table entries and 128 KiB
per expanded bundle. The keyword `max_expanded_bytes` accepts only a strict
integer from 1 through 1 MiB, so a consumer may tighten the expanded budget but
cannot increase it. Exact expanded UTF-8/JCS size is checked before repeated
certificates are copied. Encoder and legacy-list reads enforce expanded limits
as well. The codec snapshots JSON before interpreting references, retaining
numeric types until strict reference validation.

This is a storage representation, not a wire contract or authorization result.
It preserves metadata without certifying its meaning. Every consumer must still
run its original closed schemas, pinned Root/signature/checkpoint/history checks,
current time, authorization, revocation, epoch, owner and source fences after
decoding. The helper imports no service store and performs no I/O or writes.
Consumers remain responsible for allocating their non-history row budget,
checking the complete expanded row/response, and checking both the complete
physical JSON document and actual Firestore SDK encoding against the unchanged
768 KiB storage ceiling. This module alone does not enable a store migration or
change an existing route, read response limit or Worker.

The separate `reference_history_v2` module provides five explicitly selected
operations for larger **local** histories:

- `encode_storage_history_v2` writes only
  `folioview.reference-history.storage.v2`.
- `decode_storage_history_v2` reads that version, canonical stored bytes, legacy
  lists and storage-v1. Legacy/v1 still use at most their original 1 MiB expanded
  ceiling, even when read through this new function.
- `encode_transport_history` and `decode_transport_history` use only
  `folioview.reference-history.transport.v1`. The decoder accepts a parsed JSON
  dictionary, never raw bytes, legacy lists or an internal storage format as a
  fallback. The caller must first perform its original bounded strict HTTP parse.
- `snapshot_registry_history` takes a detached typed local list without granting
  physical storage capacity, HTTP capacity or authorization. A subsequent encoder
  can still reject that snapshot at its encoded limit.

Each new function defaults to the fixed local history ceiling of 4,198,400 bytes
(the existing Owner `openResult` history-list scale: 32 × 131,072 + 4,096).
`max_expanded_bytes` accepts only strict integers from 1 through that ceiling,
allowing callers to tighten it for their own complete-row/component budgets.
The original `reference_history` public signatures, defaults, maximum 1 MiB
expansion, and refusal of these new formats remain unchanged. Neither generic
JSON parsing nor an existing physical/HTTP budget inherits the new local ceiling.

Both new encoders keep the 768 KiB encoded-history limit, complete three-string
JWS identity, closed wrappers, first-use reference order and all original
per-bundle/count/reference guards. They retain all metadata, checkpoints and
active/revoked entries. Distinct signatures on identical payloads remain distinct
table entries; a valid 32-generation history can therefore still exceed physical
capacity and must be rejected rather than deduplicated by payload or key ID.
The 64-entry limit also remains independent of the generation count.

Consumers must separately enforce full metadata/expanded-row, raw HTTP response
and complete physical JSON/actual SDK budgets, then run every original schema,
Root, signature, history, time, owner, epoch, revocation and current-source check.
Any storage-v2 consumer must deploy compatible readers and retain a compatible
rollback floor before enabling writers. This foundation does not select a new
route, activate a writer, migrate data, change a Worker or establish end-to-end
large-history acceptance for any service or client.

Device signatures may authorize only the named task versions, execution epoch,
resource versions, agent keys, capabilities, expiry and owner writeback recipients.
A root-certified agent identity by itself does not authorize reading content.
Grants are bounded by current consent, the refresh family's absolute expiry and
certificate expiry, with a maximum of 30 days. Result recipients must be the
grant's exact active owner device/recovery set; agent recipients are rejected.
Every object requires owner device and recovery recipients. Adding an agent to
a task/resource requires a matching verified read grant. Historical reshare
requires explicit selected-history consent. The current grant has no result-read
capability, so result reshare to an agent is rejected.

For a new write, derive `EnvelopeExpectation` from authenticated ownership and
current database/immutable Run state. Never copy the incoming packet's own
claims into those expectations. Then:

```python
from folioview_shared.encrypted import CONTRACT_VERSION
from folioview_shared.encrypted.envelope import verify_carrier, validate_write_transition

# registry, grant and expectation come from the trusted enrollment/auth/state path.
verified = verify_carrier(
    request_bytes,
    registry=registry,
    expectation=expectation,
    grant=grant,  # Required for agent result writes; read_grants authorizes readers.
    now=now_epoch_seconds,
    contract_header=CONTRACT_VERSION,
)
validate_write_transition(verified.context, current_revision=stored_revision)
```

This is a pure validation sequence, not an HTTP handler or transaction. A
`VerifiedGrant` is a validation snapshot, not a durable authorization capability.
For **every** operation, the service must validate the current user/token,
connection, consent/refresh family, grant/execution/source fences, and exact
audience/scopes; reverify the raw signed grant against that state and the current
registry. Recheck fences and CAS inside the committing transaction. A still-valid
signature or unchanged registry digest cannot reveal a business grant revocation,
paused task or source fence stored elsewhere. No authorization cache keyed only
by envelope fingerprint or stable operation ID is permitted.

`verify_carrier` checks a **new write** with current certified keys. It must not
be used as the only stored-history verifier: retained author proofs and the
client's prior root/checkpoint history can establish who signed a historical
object, while current service permission independently controls whether it can
be retrieved. A key's later revocation does not erase data already disclosed.
Manifest component structural/fingerprint binding and retained author signature
checks are separate operations for that reason. A Run's initial identity and
Begin fingerprint must be independently pinned by its requester; hashing a
server descriptor alone does not authenticate server-chosen metadata.

Public verification validates structure, algorithm, trusted author signature,
canonical AAD, certified recipients and bindings. It **cannot** validate the GCM
tag or decrypted payload. A valid author can sign an invalid ciphertext. The
storage receipt confirms only the exact saved ciphertext and public metadata.
On the trusted endpoint, verify the outer author proof before `decrypt_jwe`;
decryption validates the AEAD tag and the typed private wrapper. Schemas reject
raw HTML and unsafe link destinations conservatively, but clients must still
use a safe Markdown renderer and must not fetch arbitrary links automatically.

Private functions accepting a private JWK are local trusted-client primitives.
Do not expose a generic sign/decrypt HTTP endpoint or agent tool. This foundation
does not implement a key archive, trusted helper delivery, persistent Muse keys,
browser unlock/recovery UX, unattended execution or production OAuth/Firebase.

## Replay, revisions and byte limits

Persist the **original complete carrier bytes** in the trusted client's outbox
before sending. Retry sends those bytes, not a fresh encryption of equivalent
plaintext. The operation fingerprint is SHA-256 over ASCII
`protected + "." + payload`; valid ES256 high/low-S variants have the same
identity. It is not proof of authorization or a plaintext hash.

Stores use `operation_namespace(context)` including owner, vault, connection,
grant, task, Run, operation type and stable operation ID. After current
authorization and signature checks, identical input returns the original saved
11-field receipt. Changed ciphertext/bindings under that operation ID conflict.
Keep receipts immutable even after later revisions. `check_operation_replay`
checks identity/binding; it neither performs authorization nor creates a record.

Each Run has one initial result; revisions use expected-version CAS and keep its
Run/result ID. A delivery reshare keeps business revision unchanged, increments
delivery revision, names the exact prior envelope fingerprint and needs a fresh
key/reader authorization check. The service must enforce unique initial writes,
CAS and atomic operation/receipt/result storage; shared predicates do not provide
concurrency control.

| Boundary                                                               | Maximum UTF-8/encoded bytes |
| ---------------------------------------------------------------------- | --------------------------: |
| Public context                                                         |                      16,384 |
| Control JWS / registry bundle                                          |            65,536 / 131,072 |
| Private task / result wrapper                                          |                 65,536 each |
| Private resource wrapper                                               |                     196,608 |
| Complete signed carrier                                                |                     524,288 |
| Complete HTTP write body                                               |                     589,824 |
| Immutable manifest / complete read response                            |         262,144 / 1,048,576 |
| Stored document, application JSON **and** actual SDK Document protobuf |                786,432 each |

At most 8 recipients, 10 resources per grant/Run, 20 JSON container levels and
safe JSON integers are accepted. Enforce the raw HTTP byte ceiling with
`read_bounded`/`strict_json_loads` before parsing nested JWS/JWE; canonical size
checks cannot account for incoming whitespace. Count the whole outer request
and response, including metadata/base64/signatures, not only ciphertext.

`check_document_budget` requires the consuming store's actual complete Firestore
Document encoding, including document name/field overhead. It does not estimate
SDK overhead or prove that the caller supplied the correct document. Encode the
exact write, then check it. The 768 KiB cap leaves 256 KiB below 1 MiB; consumer
storage/index limits still apply. Manifest pages contain one complete component,
not arbitrary partial ciphertext chunks. No raw input or crypto diagnostics are
included in `ContractError` responses or logs by this package.

## Verification

Run shared tests through `python scripts/test_services.py --service common` in
the existing development environment, and repository checks with `npm run check`.
Tests cover synthetic owner/device/recovery/multiple agent keys, independent
Node WebCrypto vectors, strict parsing, grants/revocation, binding substitutions,
AEAD failure, exact retries, original receipts, CAS and message/storage budgets.

Committed public Node fixtures are always verified/decrypted in Python CI.
An additional Python-to-Node test can be enabled with an isolated fixture-tool
install; see [interop instructions](../../tests/interop/README.md). The two-way
test uses only publicly known synthetic test keys and an anonymous pipe. This
does not claim a new real-Muse run or browser key-management implementation.

The separate [persistent content and operation-proof profile](docs/persistent-content.md)
provides Root-approved exact deliveries, current Agent request proofs and frozen
manifest contracts. It does not change P1 grants or enable any consumer.

Owner-approved 90-day credential leases are documented in the
[credential lifecycle contract](docs/agent-credentials.md). The profile is additive; consumers must
implement atomic replacement and current-generation fences before enabling it.

The additive [Owner/provider current slot contract](docs/agent-credentials.md#ownerprovider-current-connection-slot)
provides pure reviewed replacement/disconnect plans and a live slot fence. It does not
change existing consumers, migrate connections or merge legacy task/resource scopes.

The additive [task-center lifecycle contract](docs/persistent-content.md#task-center-extension)
separates tasks, zero-to-many canonical assignments, immutable run attribution,
verified trigger sources and coupled trash/restore/purge fences. It enables no
consumer, native dispatch, migration or deletion on import.

The [Owner-only display-name profile](docs/persistent-content.md#owner-only-display-names)
adds small independently versioned encrypted source aliases. It does not modify
financial resources, Agent inputs, grants or Root history, and enables no consumer.
