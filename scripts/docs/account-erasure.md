# Account erasure and restore

Use the service release containing each operator adapter and a Python environment with the
project's service dependencies. The operator works in a restricted environment. Keep the
request register on a private encrypted volume, outside the application databases and
their rollback/restore set. Its protected contents include subject identities and applicable
email delivery references. Restrict its copies, maintain their currency and give them their own
deletion procedure. The command prints aggregate results and a random case ID.

## Reviewed account request

1. Verify the requesting person's control of the account through an authenticated confirmation or
   a challenge to the verified account address. Confirm the person wants the whole account erased.
   Use the individual resource action for a narrower request. Resolve the exact production project
   and Firebase UID. Check deployments, legacy locations, and external processors for this case.
2. Run `python scripts/account_erasure.py register --register FILE --project PROJECT` with
   a JSON object containing `uid` and `email` on standard input. The tool independently checks
   Firebase's verified Google identity and stores its subject. Use the returned `--case ID`
   with `inventory`, `suspend` and `erase` in that order, using the same project and register.
   Suspension disables the account and revokes refresh tokens. Drain in-flight private writes.
   Hub must fence independent agent credentials and scheduled/retried work before other services
   can finish. Keep access suspended through verification. Run the operator sweep again on
   interruption or a pending fence. Read every error as an incomplete case.
3. Erase covers Hub, Portfolio, Config, and the current and legacy User databases. Each adapter
   restricts writes to the reviewed scope. The coordinator inventories all targets before the
   first removal, verifies that Hub has blocked account writes, and saves applicable invitation
   delivery IDs before User records disappear. It clears upstream services first, then clears
   Hub and verifies that its drain interval has elapsed before releasing the write hold.
   It independently inventories every target again before recording the latest server read time.
   A missing adapter, incomplete read or residual row prevents a successful database result.
4. Run `retire-identity` after database verification. The operator checks the same disabled
   Google account again, removes its Firebase identity, and checks that a new read reports it
   missing. A retry can verify an identity already removed. Keep the case open for other copies.
5. Review the subject's applicable log destinations (including Cloudflare exports), retained
   history, backups, mail and support records, including register copies. Where selective erasure
   is unavailable, wait for actual expiry and verify it. Document evidence in a restricted case
   system. For applicable Resend deliveries, use intake references from the register and obtain
   processor confirmation. Data originally shared with another provider under the user's account
   follows its own controls. Keep independent external evidence scoped and avoid duplicating content.
6. Run `close` with reviewed evidence references on standard input, e.g.
   `{"logs":"case-log-review","backups":"case-backup-review","processors":"case-processor-review","registerCopies":"case-register-review"}`.
   The operator attests to the scoped external checks with these references. The tool independently
   verifies current database absence, identity absence, and that the relevant Firestore historical
   windows have passed the confirmed removals. It removes the case identity and delivery locators
   from the active register and retains a project-level restoration cutoff. Confirm completion to
   the user after all applicable copies resolve.

## Recovering an older backup

Keep the restored services offline. Use a current, independently
retained register and all restored service databases, including the legacy User store. Inventory
with `restore-check --project SOURCE --restored-project TARGET --register FILE`. This uses verified
identity mappings saved when the requests were accepted, even if Firebase no longer has the account.
Any remaining record, unknown owner or incomplete scan blocks release.

The final check also covers people who kept their accounts and erased an individual item. It
compares the restored documents with the surviving source so an old snapshot cannot restore a
removed task, source, archive or list entry. Review differences in isolation. A regular edit can
also cause a difference. If a surviving authority or its identity cannot be verified, keep the
copy offline. Hold private writes during final verification and routing handoff.

For native Firestore backups, restore each of the four databases in the source project to
`erasure-restore-BATCH-default`, `erasure-restore-BATCH-user-data`,
`erasure-restore-BATCH-portfolio` and `erasure-restore-BATCH-agent-hub`. Select one batch
of 6–24 lowercase letters and digits. Keep these database IDs out of routing and restrict IAM
to the recovery operator. Set `--restored-project` to the source project and supply
`--restore-batch BATCH`. The check compares each database's provider-issued backup provenance to
its original database. The operator only reads and clears the named copies during this workflow.
[Firestore backup restore](https://docs.cloud.google.com/firestore/docs/reference/rest/v1/projects.databases/restore)

Use `restore-scrub` with the same arguments to reapply affected requests using each service's
own backend. For a separate restore project, its Resource Manager label `foliocrew-restore-of` must identify the source.
Restrict who can label the target, keep application identities disconnected, and use credentials
with write access only in the isolated target. For a disposable loopback emulator, choose a
`demo-` target. After reapplying, read every target again and check an unrelated control account.
Recheck immediately before admitting traffic, coordinating new erasure requests with cutover.
Keep unregistered backups and exports of unknown provenance out of service. After the last
per-account suppression information is removed, restore eligibility requires verified backup
lineage newer than the non-identifying project cutoff. An export with unverifiable lineage
remains quarantined. This tool returns an admission result; it never changes traffic routing.
