const assert = require("node:assert/strict");
const test = require("node:test");
const { createBrowserFixture } = require("./vault-browser-fixture.cjs");
const { createOwner, decoded } = require("./full-flow-crypto-fixture.cjs");
const { lifecycleState } = require("./vault-key-renewal-fixture.cjs");

let browser;
test.before(async () => {
  browser = await createBrowserFixture();
});
test.after(async () => {
  await browser?.close();
});
const sources = "a".repeat(64);

async function initialize({ client, store }) {
  const { h } = browser;
  const owner = await createOwner(h),
    storage = store();
  const session = client(owner.uid, storage);
  const transient = await session.beginCreate(owner.material());
  const vault = {
    vaultId: transient.vaultId,
    rootJwk: transient.rootJwk,
    rootKeyId: transient.rootKeyId,
    registryHistory: [transient.registryBundle],
    archive: transient.archive,
    version: 1,
  };
  await session.acceptVault(vault);
  const state = await lifecycleState(h, { vault });
  const head = {
    registryEpoch: 1,
    registrySequence: 1,
    keyEpoch: state.keyEpoch,
    checkpointDigest: state.checkpointDigest,
  };
  async function evidence(request, changes = {}) {
    return {
      contractVersion: request.contractVersion,
      profile: request.profile,
      ownerSubject: request.ownerSubject,
      vaultId: request.vaultId,
      rootKeyId: vault.rootKeyId,
      requestDigest: await h.core.sha(h.core.canonical(request)),
      vaultVersion: vault.version,
      registry: head,
      registryStart: null,
      archive: { state: "active", version: 1, digest: state.archiveDigest },
      device: "active",
      sourcesDigest: sources,
      verifiedAt: 1000,
      expiresAt: 1040,
      ...changes,
    };
  }
  return {
    h,
    uid: owner.uid,
    material: owner.material,
    storage,
    session,
    vault,
    state,
    head,
    evidence,
  };
}

function noPage() {
  assert.fail("Unexpected registry page request");
}

test("Worker requires verified local archive and accepts one matching nonce without requesting pages or changing local pins", async () => {
  await browser.withDatabase(async (db) => {
    const { session, state, vault, storage, evidence, h } = await initialize(db);
    const transport = { evidence, page: noPage };
    await assert.rejects(session.verifyUserRecovery(transport, sources), /locked/);
    await session.verifyLifecycle(vault, state);
    const key = vault.archive.ownerSubject + ":pin";
    const before = await storage.get(key);
    let original;
    assert.equal(
      await session.verifyUserRecovery(
        {
          ...transport,
          evidence: async (request) => {
            original = await evidence(request);
            return original;
          },
        },
        sources,
      ),
      "unchanged",
    );
    await assert.rejects(
      session.verifyUserRecovery({ ...transport, evidence: () => original }, sources),
      /untrusted_vault/,
    );
    assert.equal(await session.verifyUserRecovery(transport, "b".repeat(64)), "refresh-required");
    await assert.rejects(
      session.verifyUserRecovery(
        {
          ...transport,
          evidence: (request) =>
            evidence(request, {
              archive: { state: "active", version: 1, digest: "b".repeat(64) },
            }),
        },
        sources,
      ),
      /rollback_detected/,
    );
    assert.deepEqual(await storage.get(key), before);
    assert.equal(
      before.checkpointDigest,
      await h.core.sha(h.core.canonical(decoded(vault.registryHistory[0].checkpoint))),
    );
  });
});

test("Worker verifies contiguous signed pages against one target and keeps the original pin until a full refresh", async () => {
  await browser.withDatabase(async (db) => {
    const { h, uid, material, session, vault, state, head, evidence, storage } =
      await initialize(db);
    await session.verifyLifecycle(vault, state);
    let current = vault;
    const bundles = [];
    for (let i = 0; i < 2; i++) {
      const other = new h.core.VaultCore(uid, () => 1000);
      await other.unlock(current, material());
      const update = await other.prepareDeviceRegistration(current);
      bundles.push(update.registryBundle);
      current = {
        ...current,
        version: current.version + 1,
        registryHistory: [...current.registryHistory, update.registryBundle],
      };
    }
    const checkpoint = decoded(bundles.at(-1).checkpoint);
    const target = {
      ...head,
      registrySequence: checkpoint.registrySequence,
      checkpointDigest: await h.core.sha(h.core.canonical(checkpoint)),
    };
    function page(request) {
      return {
        ...request,
        rootKeyId: vault.rootKeyId,
        bundles: [bundles[request.base.registrySequence - 1]],
      };
    }
    const read = (request) =>
      evidence(request, { registry: target, vaultVersion: current.version });
    const calls = [];
    const pinKey = vault.archive.ownerSubject + ":pin",
      pinned = await storage.get(pinKey);
    assert.equal(
      await session.verifyUserRecovery(
        {
          evidence: read,
          page: (request) => {
            calls.push(request);
            return page(request);
          },
        },
        sources,
      ),
      "registry-verified",
    );
    assert.deepEqual(
      calls.map(({ base }) => base.registrySequence),
      [1, 2],
    );
    assert.deepEqual(
      calls.map((request) => request.target),
      [target, target],
    );
    assert.deepEqual(await storage.get(pinKey), pinned);
    for (const corrupt of [
      (value) => {
        value.target = { ...target, registrySequence: 4 };
      },
      (value) => {
        value.ownerSubject = "b".repeat(64);
      },
      (value) => {
        value.bundles = [bundles.at(-1)];
      },
      (value) => {
        value.bundles[0].checkpoint.signature = "A".repeat(86);
      },
    ]) {
      await assert.rejects(
        session.verifyUserRecovery(
          {
            evidence: read,
            page: (request) => {
              const output = structuredClone(page(request));
              corrupt(output);
              return output;
            },
          },
          sources,
        ),
        /registry_conflict|invalid_signature/,
      );
    }
    await assert.rejects(
      session.verifyUserRecovery(
        {
          evidence: read,
          page: (request) => {
            browser.time(1040);
            return page(request);
          },
        },
        sources,
      ),
      /untrusted_vault/,
    );
    browser.time(1000);
    let leakedSignal;
    await assert.rejects(
      session.verifyUserRecovery(
        {
          evidence: read,
          page: (_request, signal) => {
            leakedSignal = signal;
            session.lock();
            return page(_request);
          },
        },
        sources,
      ),
      /locked|abort/i,
    );
    assert.equal(leakedSignal?.aborted, true);
  });
});
