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
transaction boundary. The cutover must install the projection atomically with
each recovered authority change or keep the route disabled. The original full
recovery and legacy authority routes continue through the transition.
