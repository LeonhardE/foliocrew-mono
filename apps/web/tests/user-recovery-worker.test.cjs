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

test("the new registry start requires a fresh original Passkey and preserves current pins", async () => {
  await browser.withDatabase(async (db) => {
    const { vault, state, material, session, storage } = await initialize(db);
    await session.verifyLifecycle(vault, state);
    const key = vault.archive.ownerSubject + ":pin";
    const before = await storage.get(key);
    const expired = await session.reviewUserRegistryTransition(state);
    browser.time(expired.expiresAt);
    await assert.rejects(
      session.signUserRegistryTransition(expired, material()),
      /untrusted_vault/,
    );
    browser.time(1000);
    const first = await session.reviewUserRegistryTransition(state);
    await assert.rejects(
      session.signUserRegistryTransition(first, {
        ...material(),
        secret: new Uint8Array(32).buffer,
      }),
      /unlock_failed/,
    );
    await assert.rejects(session.signUserRegistryTransition(first, material()), /untrusted_vault/);
    const review = await session.reviewUserRegistryTransition(state);
    const packet = await session.signUserRegistryTransition(review, material());
    const transition = decoded(packet.signedTransition);
    assert.equal(packet.operationId, review.operationId);
    assert.equal(transition.previousVaultVersion, vault.version);
    assert.equal(transition.nextVaultVersion, vault.version + 1);
    assert.equal(transition.archive.digest, state.archiveDigest);
    assert.deepEqual(transition.ownerKeyIds, review.ownerKeyIds);
    assert.equal(decoded(packet.firstBundle.checkpoint).previousDigest, before.checkpointDigest);
    assert.equal(transition.nextHead.registryEpoch, 2);
    assert.deepEqual(await storage.get(key), before);
    assert.ok(!JSON.stringify(packet).includes("rootPrivateJwk"));
    assert.ok(!JSON.stringify(packet).includes(vault.archive.credentialId));
    await assert.rejects(session.signUserRegistryTransition(review, material()), /untrusted_vault/);

    const { spawnSync } = require("node:child_process");
    const { resolve } = require("node:path");
    const repository = resolve(__dirname, "../../..");
    const python =
      process.env.FOLIOVIEW_TEST_PYTHON ||
      resolve(repository, "services/market-data-service/.venv/bin/python");
    const script = `
import json, sys
from folioview_shared.encrypted.authority import verify_registry
from folioview_shared.encrypted.private_resources import PrivateRegistryCursor, verify_private_registry_transition
v = json.load(sys.stdin)
args = dict(root_jwk=v['vault']['rootJwk'], pinned_root_key_id=v['vault']['rootKeyId'],
            owner_subject=v['owner'], vault_id=v['vault']['vaultId'], now=1000)
previous = verify_registry(v['vault']['registryHistory'][0], **args)
next_start = verify_private_registry_transition(
    v['packet']['signedTransition'], first_bundle=v['packet']['firstBundle'],
    authenticated_start=v['target'], previous=PrivateRegistryCursor(previous, 1), **args,
)
print(json.dumps(next_start.head()))
`;
    const checked = spawnSync(python, ["-c", script], {
      cwd: repository,
      env: { ...process.env, PYTHONPATH: resolve(repository, "services/common") },
      input: JSON.stringify({
        vault,
        packet,
        target: transition.nextHead,
        owner: vault.archive.ownerSubject,
      }),
      encoding: "utf8",
      timeout: 10000,
    });
    assert.equal(checked.status, 0, checked.stderr || checked.error?.message);
    assert.deepEqual(JSON.parse(checked.stdout), transition.nextHead);
  });
});

test("Worker verifies the fresh User epoch against the original pinned Root, archive and nonce", async () => {
  await browser.withDatabase(async (db) => {
    const { session, state, vault, storage, evidence, material } = await initialize(db);
    await session.verifyLifecycle(vault, state);
    const key = vault.archive.ownerSubject + ":pin";
    const pinned = await storage.get(key);
    const review = await session.reviewUserRegistryTransition(state);
    const packet = await session.signUserRegistryTransition(review, material());
    const { nextHead, archive } = decoded(packet.signedTransition);
    let lastStarts = 0;
    const transport = {
      evidence: (request) =>
        evidence(request, { registry: nextHead, registryStart: nextHead, vaultVersion: 2 }),
      start: (request) => {
        lastStarts++;
        return {
          ...request,
          rootKeyId: vault.rootKeyId,
          vaultVersion: 2,
          archive,
          registry: nextHead,
          registryStart: nextHead,
          sourcesDigest: sources,
          rootJwk: vault.rootJwk,
          signedTransition: packet.signedTransition,
          firstBundle: packet.firstBundle,
        };
      },
      page: noPage,
    };
    assert.equal(await session.verifyUserRecovery(transport, sources), "registry-verified");
    assert.equal(lastStarts, 1);
    assert.equal(
      await session.verifyUserRecovery({ evidence: transport.evidence, page: noPage }, sources),
      "refresh-required",
    );
    for (const alter of [
      (start) => (start.nonce = "a".repeat(32)),
      (start) => (start.rootKeyId = "k".repeat(43)),
      (start) => (start.registryStart = { ...nextHead, registryEpoch: 1 }),
      (start) => (start.signedTransition.signature = "A".repeat(86)),
      (start) => (start.firstBundle.entries[0].active = false),
    ]) {
      await assert.rejects(
        session.verifyUserRecovery(
          {
            ...transport,
            start: (request) => {
              const value = structuredClone(transport.start(request));
              alter(value);
              return value;
            },
          },
          sources,
        ),
        /untrusted_vault|registry_conflict|invalid_signature|invalid_registry/,
      );
    }
    assert.deepEqual(await storage.get(key), pinned);
  });
});
