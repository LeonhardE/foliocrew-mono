# Personal Agent runtime and native integration

The current execution host is the user's Muse or ChatGPT environment. Use the
[reviewed private client](agent-client.md), [credential lifecycle](persistent-api.md#agent-owned-credential-lifecycle)
and [Web authorization](../../../apps/web/docs/agent-integration.md). The old fixed
browser runtime is retired, including its Worker, IndexedDB key profile, controller
page, setup bridge and recovery API.

## Account transport

Native OAuth grants only `runtime:connect`, with a preregistered client/provider and
fixed callback. A dependency-free account-link page at `/agent/v3/account/consent.html`
opens the original trusted Owner page. Its source/origin/request/nonce-bound channel
permits only account `pending`/`approve`; it never stores Agent credentials. The old
account-consent page URL is a narrow alias for finishing an already-issued window.
All browser Agent runtime/config/setup URLs remain absent.

The bootstrap-only `/mcp/v3` request body has a five-second total read deadline,
including time between streamed chunks. The original byte budget is checked before
extending the buffer. Timeout and overflow return fixed, non-cacheable transport
errors before the SDK handles the request; disconnect and external cancellation stop
without forwarding partial content. This body deadline does not shorten SDK processing
or replace its original token, Owner, origin and permission checks.

Multiple account-link windows can use separate browser bindings. After all serving Hub revisions
can read both cookie formats, set `HUB_NATIVE_SCOPED_CONSENT_COOKIES_ENABLED=1` to issue each
cookie for that request’s pending and approval paths. Turning off the flag restores issuance of
the legacy cookie while existing scoped windows can finish. Keep the compatible reader until
30 minutes after the last scoped cookie was issued before reverting to an older binary.

### Branded native origin

The existing `HUB_OAUTH_ISSUER` remains the default origin. Set
`HUB_NATIVE_EDGE_PUBLIC_KEY` to the base64url Ed25519 public key for the
dedicated Cloudflare Agent Worker to prepare `https://mcp.foliocrew.app`.
The native edge proof binds the upstream and public origins, method, exact
path and query, browser Origin, and timestamp. Only allowlisted public protocol
paths accept it, and an invalid or missing branded proof cannot select the
second issuer. Keep the matching private key in the Worker secret.

The branded issuer has its own OAuth resource and MCP boundary. New branded
connections retain that resource in storage. Existing connections retain
their original issuer, and Owner approvals use the resource recorded for the
chosen connection. Use both original and branded discovery, OAuth and signed
runtime tests before publishing the branded default. Once branded
connections exist, use a compatible revision for rollback and keep their
brand routing and key valid.

## First pairing

Only explicit user connection or reauthorization creates a ten-minute setup. The
private host creates fresh signing/encryption keys and a temporary pairing secret,
submits an opaque encrypted public offer, and shows the Owner its authorization link.
The existing Owner login and decryption Passkey approve the exact client/provider,
vault, generation and reviewed scope. The Agent verifies the encrypted Root anchor
and current lease before activating its locally stored keys.

## Cryptography and storage

See [private client storage](agent-client.md) for Node/POSIX prerequisites, private
permissions and load-only failures. Private keys stay on the host; Hub stores public
records and ciphertext. Host tools can read the host's private files under the accepted
personal trust model. File retention and native schedule availability are not guaranteed
by the platform and require live host validation.

## Execution and schedules

Native Agent schedules invoke the fixed client operations to fetch/decrypt approved
inputs, run analysis and return Owner-encrypted reports. No browser tab, platform VM,
TCP proxy or scheduler is required. A stored plan statement is the Agent's signed report;
actual Hub Run/result receipts are separate evidence and do not attest a native task.

Missing/corrupt/expired/rejected credentials stop execution and ask the user to authorize
again in FolioView. Reauthorization restores only still-approved scope and original
assignments after verifying the signed lineage. No recovery codes/files are given to
users for Agent credentials. Original Owner history and revocations remain intact.

## Distribution and rollout

`account-link/build.mjs` copies only reviewed first-party account modules and produces
a hash manifest. No crypto SDK or browser key worker is bundled there. The separately
pinned private client is distributed by the existing Hub image. Feature gates default
off; the service scales to zero under the existing deployment structure. Deployment,
real host compatibility and cross-day/native acceptance require a separate approved window.

The managed Hub target also supplies `HUB_AGENT_OWNED_ALLOWED_OWNER_SUBJECTS_JSON`,
a bounded list of reviewed Owner subject hashes. Its default empty list denies all;
enabling personal Agent mode requires a nonempty list. A restricted rollout admits
only those accounts to native approval, credential setup/replacement and current
credential execution. Removing an account also fences existing native tokens and
managed execution; Owner history and disconnect remain available. Malformed lists
fail closed. Installations that omit this optional restriction retain their prior
admission behavior. The list grants no resource consent and bypasses no Root,
lease, scope, freshness or revocation checks. No new cloud resource is required.

### Expired OAuth data

The Hub retention worker inspects both native and foreground OAuth stores. It clears expired
authorization attempts, unused one-time codes and credentials after their final use. The
same job leaves current connections, authorization generations and reports accessible.

A spent code or rotated refresh token can still detect replay against its live credential
family. Until that family expires, the worker retains the lookup hash, protocol bindings
and revocation state needed by the original flow. Rotating a native refresh token can
extend this window. The stored deadline on a compacted record is its next cleanup date.
The protocol always rejects it for data access.

Native OAuth also lets an expired token disconnect the same enrolled agent. If that
connection can still be revoked, the worker retains minimal revocation references even
after the transport expires. After the family's deadline, disconnecting the connection
or replacing its authorization generation releases those references on the next run.
Verified account erasure includes these references at any time. The worker reports
aggregate task and source counts. For OAuth it reports only `ok` or `review_required`.
Unexpected results or storage errors produce a fixed review status and a nonzero exit.
