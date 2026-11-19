import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { digest } from "../dist/core.mjs";
import { verifyOwnerRecoveryEvidence } from "../dist/private-recovery.mjs";

const vector = JSON.parse(
  await readFile(
    new URL("../../../services/common/tests/fixtures/private_resources.json", import.meta.url),
    "utf8",
  ),
);

test("the existing browser canonical digest matches the additive private-resource vectors", async () => {
  assert.equal(await digest(vector.request), vector.decision.requestDigest);
  assert.equal(await digest(vector.recovery), vector.evidence.requestDigest);
  assert.equal(await digest(vector.index.toReversed()), vector.evidence.sourcesDigest);
  assert.notEqual(
    await digest({ ...vector.request, attemptId: "different_attempt_id_0001" }),
    vector.decision.requestDigest,
  );
});

const options = {
  request: vector.recovery,
  pinnedRootKeyId: vector.evidence.rootKeyId,
  now: vector.evidence.verifiedAt + 1,
};
const code = (value) => ({ code: value });

test("shared browser recovery verifies the authenticated nonce, Root, and exact lifetime", async () => {
  const evidence = structuredClone(vector.evidence);
  const pending = verifyOwnerRecoveryEvidence(evidence, options);
  evidence.registry.registrySequence++;
  assert.deepEqual(await pending, vector.evidence);
  await assert.rejects(
    verifyOwnerRecoveryEvidence(vector.evidence, {
      ...options,
      request: { ...options.request, nonce: "different_synthetic_nonce_0001" },
    }),
    code("recipient_binding_mismatch"),
  );
  await assert.rejects(
    verifyOwnerRecoveryEvidence(vector.evidence, { ...options, pinnedRootKeyId: "x".repeat(43) }),
    code("untrusted_key"),
  );
  await assert.rejects(
    verifyOwnerRecoveryEvidence(vector.evidence, { ...options, now: vector.evidence.expiresAt }),
    code("authorization_unavailable"),
  );
  await assert.rejects(
    verifyOwnerRecoveryEvidence({ ...vector.evidence, device: "inactive" }, options),
    code("key_authorization_required"),
  );
});

test("recovery rejects a malformed or rolled-back registry floor and archive boundary", async () => {
  const old = structuredClone(vector.evidence);
  const check = (value) => verifyOwnerRecoveryEvidence(value, { ...options, previous: old });
  await assert.rejects(
    check({ ...old, vaultVersion: old.vaultVersion - 1 }),
    code("rollback_detected"),
  );
  await assert.rejects(
    check({ ...old, archive: { ...old.archive, version: 1 } }),
    code("rollback_detected"),
  );
  await assert.rejects(
    check({ ...old, registry: { ...old.registry, checkpointDigest: "a".repeat(64) } }),
    code("rollback_detected"),
  );
  await assert.rejects(
    check({ ...old, registry: { ...old.registry, registryEpoch: 2 } }),
    code("registry_conflict"),
  );
  const start = {
    ...old.registry,
    registryEpoch: 2,
    registrySequence: old.registry.registrySequence + 1,
  };
  const accepted = {
    ...old,
    vaultVersion: old.vaultVersion + 1,
    registry: start,
    registryStart: start,
  };
  assert.deepEqual(await check(accepted), accepted);
  await assert.rejects(
    check({ ...accepted, registryStart: { ...start, checkpointDigest: "b".repeat(64) } }),
    code("registry_conflict"),
  );
  await assert.rejects(check({ ...old, plaintext: "synthetic" }), code("invalid_schema"));
});

test("the browser recovery schema keeps the shared definitions unchanged", async () => {
  const browser = JSON.parse(
    await readFile(new URL("../private-recovery.schema.json", import.meta.url), "utf8"),
  );
  const shared = JSON.parse(
    await readFile(
      new URL(
        "../../../services/common/folioview_shared/encrypted/private_resources.json",
        import.meta.url,
      ),
      "utf8",
    ),
  );
  for (const name of [
    "PrivateResourceVersion",
    "PrivateResourceTime",
    "PrivateRegistryHead",
    "PrivateArchiveBoundary",
    "PrivateRecoveryRequest",
    "PrivateRecoveryEvidence",
  ])
    assert.deepEqual(browser.$defs[name], shared.$defs[name]);
});
