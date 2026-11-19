const assert = require("node:assert/strict");
const test = require("node:test");
const { createBrowserFixture } = require("./vault-browser-fixture.cjs");
const { createOwner, decoded } = require("./full-flow-crypto-fixture.cjs");
const { lifecycleState, renewalAccepted } = require("./vault-key-renewal-fixture.cjs");

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

async function signedTransition(h, uid, vault, state, material, signer) {
  const root = signer ?? new h.core.VaultCore(uid, () => 1000);
  if (!signer) await root.unlock(vault, material());
  const previous = vault.registryHistory.at(-1);
  const entries = previous.entries.filter(
    ({ active, certificate }) =>
      active && ["device_sig", "device_enc", "recovery_enc"].includes(decoded(certificate).role),
  );
  const firstBundle = await root.bundle(entries, root.registry);
  const head = async (bundle, registryEpoch) => {
    const cp = decoded(bundle.checkpoint);
    return {
      registryEpoch,
      registrySequence: cp.registrySequence,
      keyEpoch: cp.keyEpoch,
      checkpointDigest: await h.core.sha(h.core.canonical(cp)),
    };
  };
  const operationId = "synthetic_owner_registry_transition";
  const payload = {
    contractVersion: h.types.CONTRACT,
    profile: "folioview.owner-registry-transition.v1",
    ownerSubject: vault.archive.ownerSubject,
    vaultId: vault.vaultId,
    rootKeyId: vault.rootKeyId,
    operationId,
    previousVaultVersion: vault.version,
    nextVaultVersion: vault.version + 1,
    previousHead: await head(previous, 1),
    nextHead: await head(firstBundle, 2),
    ownerKeyIds: entries.map(({ certificate }) => decoded(certificate).keyId).sort(),
    archive: { state: "active", version: state.lifecycleVersion + 1, digest: state.archiveDigest },
    issuedAt: decoded(firstBundle.checkpoint).issuedAt,
  };
  const signedTransition = await new h.jose.FlattenedSign(
    new TextEncoder().encode(h.core.canonical(payload)),
  )
    .setProtectedHeader({
      alg: "ES256",
      kid: vault.rootKeyId,
      typ: "fv-control+jws",
      cty: "application/json",
    })
    .sign(root.root);
  return { operationId, signedTransition, firstBundle };
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

test("an existing Owner-signed registry start passes the shared verifier", async () => {
  await browser.withDatabase(async (db) => {
    const { vault, state, material, uid, h } = await initialize(db);
    const packet = await signedTransition(h, uid, vault, state, material);
    const transition = decoded(packet.signedTransition);
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

test("the original Passkey opens a transferred vault and upgrades the stored registry floor", async () => {
  await browser.withDatabase(async (db) => {
    const { session, state, vault, storage, material, uid, h } = await initialize(db);
    await session.verifyLifecycle(vault, state);
    const packet = await signedTransition(h, uid, vault, state, material);
    const { nextHead, archive } = decoded(packet.signedTransition);
    const current = {
      ...vault,
      version: vault.version + 1,
      registryHistory: [packet.firstBundle],
      userAuthority: {
        signedTransition: packet.signedTransition,
        registry: nextHead,
        registryStart: nextHead,
        archive,
        sourcesDigest: await h.core.sha(h.core.canonical([])),
        sources: [],
      },
    };
    const outsider = new h.core.VaultCore(uid, () => 1000);
    assert.equal((await outsider.unlock(current, material())).needsDeviceRegistration, true);
    const corrupt = {
      ...current,
      userAuthority: { ...current.userAuthority, sourcesDigest: sources },
    };
    await assert.rejects(session.acceptVault(corrupt), /untrusted_vault/);
    await session.acceptVault(current);
    const imported = await storage.get(vault.archive.ownerSubject + ":pin");
    assert.equal(imported.registryEpoch, 2);
    assert.equal(imported.checkpointDigest, nextHead.checkpointDigest);
    session.lock();
    const reload = db.client(uid, storage);
    await assert.rejects(reload.unlock(vault, material()), /rollback_detected/);
    const verified = db.client(uid, storage);
    assert.equal((await verified.unlock(current, material())).needsDeviceRegistration, false);
  });
});

test("the original Passkey opens a renewed archive after the new epoch omits revoked certificates", async () => {
  await browser.withDatabase(async (db) => {
    const { h } = browser;
    const old = await createOwner(h);
    old.time(2000);
    browser.time(2000);
    const state = await lifecycleState(h, old);
    await old.session.unlockForKeyRenewal(old.vault, old.material(), {
      pin: old.local.pin,
      device: old.local.device,
    });
    const candidate = await old.session.prepareKeyRenewal(old.vault, state);
    const renewed = await renewalAccepted(h, old.vault, state, candidate.packet, old.now());
    const finished = await old.session.finishKeyRenewal(
      renewed.vault,
      renewed.state,
      candidate.record,
      renewed.receipt,
    );
    const signer = new h.core.VaultCore(old.uid, old.now);
    await signer.unlock(renewed.vault, old.material(), {
      pin: finished.record.pin,
      device: finished.record.device,
    });
    const packet = await signedTransition(
      h,
      old.uid,
      renewed.vault,
      renewed.state,
      old.material,
      signer,
    );
    const { previousHead, nextHead, archive } = decoded(packet.signedTransition);
    assert.equal(decoded(packet.firstBundle.checkpoint).revokedKeyIds.length, 3);
    assert.equal(packet.firstBundle.entries.length, 3);
    const current = {
      ...renewed.vault,
      version: renewed.vault.version + 1,
      registryHistory: [packet.firstBundle],
      userAuthority: {
        signedTransition: packet.signedTransition,
        registryStart: nextHead,
        registry: nextHead,
        archive,
        sources: [],
        sourcesDigest: await h.core.sha(h.core.canonical([])),
      },
    };
    const storage = db.store();
    const owner = renewed.vault.archive.ownerSubject;
    await storage.commitVault(owner, finished.record);
    const page = (request) => ({
      ...request,
      rootKeyId: current.rootKeyId,
      bundles: renewed.vault.registryHistory,
    });

    const unproven = db.client(old.uid, storage, {
      readOriginalRegistryPage: async (request) => ({
        ...page(request),
        bundles: renewed.vault.registryHistory.slice(1),
      }),
    });
    await assert.rejects(unproven.unlockForResults(current, old.material()), /registry_conflict/);

    const requests = [];
    const sameDevice = db.client(old.uid, storage, {
      readOriginalRegistryPage: async (request) => {
        requests.push(request);
        return page(request);
      },
    });
    assert.equal((await sameDevice.unlockForResults(current, old.material())).canWriteState, true);
    assert.equal((await sameDevice.acceptResultVault(current)).canWriteState, true);
    assert.equal(
      await sameDevice.acceptResultVault(current).then((value) => value.canWriteState),
      true,
    );
    assert.equal(requests.length, 1);
    assert.equal(requests[0].base, null);
    assert.deepEqual(requests[0].target, previousHead);
    const pinned = await storage.get(owner + ":pin");
    assert.equal(pinned.registryEpoch, 2);
    assert.equal(pinned.checkpointDigest, nextHead.checkpointDigest);

    const reload = db.client(old.uid, storage, { readOriginalRegistryPage: page });
    assert.equal((await reload.unlockForResults(current, old.material())).canWriteState, true);
  });
});

test("an offline original device verifies the missing old pages before advancing its stored pin", async () => {
  await browser.withDatabase(async (db) => {
    const { session, vault, storage, material, uid, h } = await initialize(db);
    const owner = vault.archive.ownerSubject;
    const pinKey = owner + ":pin";
    const before = await storage.get(pinKey);
    const local = await storage.get(owner + ":device:" + vault.vaultId);
    let advanced = vault;
    for (let i = 0; i < 3; i++) {
      const other = new h.core.VaultCore(uid, () => 1000);
      await other.unlock(advanced, material());
      const append = await other.prepareDeviceRegistration(advanced);
      advanced = {
        ...advanced,
        version: advanced.version + 1,
        registryHistory: [...advanced.registryHistory, append.registryBundle],
      };
    }
    const signer = new h.core.VaultCore(uid, () => 1000);
    await signer.unlock(advanced, material(), { pin: before, device: local.device });
    const state = await lifecycleState(h, { vault: advanced });
    await signer.verifyLifecycle(advanced, state);
    const packet = await signedTransition(h, uid, advanced, state, material, signer);
    const { nextHead, previousHead, archive } = decoded(packet.signedTransition);
    const current = {
      ...vault,
      version: advanced.version + 1,
      registryHistory: [packet.firstBundle],
      userAuthority: {
        signedTransition: packet.signedTransition,
        registryStart: nextHead,
        registry: nextHead,
        archive,
        sourcesDigest: await h.core.sha(h.core.canonical([])),
        sources: [],
      },
    };
    session.lock();

    const bases = [];
    const page = async (request, signal) => {
      assert.equal(signal.aborted, false);
      assert.deepEqual(request.target, previousHead);
      assert.equal(request.ownerSubject, owner);
      assert.equal(request.vaultId, vault.vaultId);
      const sequence = request.base.registrySequence;
      bases.push(sequence);
      assert.deepEqual(await storage.get(pinKey), before);
      return {
        ...request,
        rootKeyId: vault.rootKeyId,
        bundles: [advanced.registryHistory[sequence]],
      };
    };
    const wrong = db.client(uid, storage, {
      async readOriginalRegistryPage(request, signal) {
        const result = await page(request, signal);
        return {
          ...result,
          bundles: [advanced.registryHistory[request.base.registrySequence + 1]],
        };
      },
    });
    await assert.rejects(wrong.unlock(current, material()), /registry_conflict/);
    assert.deepEqual(await storage.get(pinKey), before);
    wrong.lock();

    bases.length = 0;
    const currentSession = db.client(uid, storage, { readOriginalRegistryPage: page });
    assert.equal((await currentSession.unlock(current, material())).needsDeviceRegistration, false);
    assert.deepEqual(bases, [1, 2, 3]);
    assert.deepEqual(await storage.get(pinKey), before);
    await currentSession.acceptVault(current);
    const committed = await storage.get(pinKey);
    assert.equal(committed.registryEpoch, 2);
    assert.equal(committed.checkpointDigest, nextHead.checkpointDigest);
    assert.deepEqual(bases, [1, 2, 3], "reuse completed proof in the same unlocked Worker");
  });
});

test("an offline Owner bridge crosses the 32-checkpoint legacy limit before pinning User epoch 2", async () => {
  await browser.withDatabase(async (db) => {
    const { session, uid, h, material, vault, storage } = await initialize(db);
    const owner = vault.archive.ownerSubject;
    const pinKey = owner + ":pin";
    const before = await storage.get(pinKey);
    const local = await storage.get(owner + ":device:" + vault.vaultId);
    const original = { ...vault, registryHistory: [...vault.registryHistory] };
    const root = new h.core.VaultCore(uid, () => 1000);
    await root.unlock(vault, material(), { pin: before, device: local.device });
    const { FlattenedSign } = await import("jose");
    for (let sequence = 2; sequence <= 32; sequence++) {
      const previous = original.registryHistory.at(-1);
      const body = {
        ...decoded(previous.checkpoint),
        registrySequence: sequence,
        previousDigest: await h.core.sha(h.core.canonical(decoded(previous.checkpoint))),
        issuedAt: 1000,
      };
      const checkpoint = await new FlattenedSign(new TextEncoder().encode(h.core.canonical(body)))
        .setProtectedHeader({
          alg: "ES256",
          kid: vault.rootKeyId,
          typ: "fv-control+jws",
          cty: "application/json",
        })
        .sign(root.root);
      original.registryHistory.push({ ...previous, checkpoint });
    }
    original.version = 32;
    const signer = new h.core.VaultCore(uid, () => 1000);
    await signer.unlock(original, material(), { pin: before, device: local.device });
    const lifecycle = await lifecycleState(h, { vault: original });
    await signer.verifyLifecycle(original, lifecycle);
    const packet = await signedTransition(h, uid, original, lifecycle, material, signer);
    const { nextHead, previousHead, archive } = decoded(packet.signedTransition);
    assert.equal(previousHead.registrySequence, 32);
    assert.equal(nextHead.registrySequence, 33);
    assert.equal(nextHead.registryEpoch, 2);
    const fresh = {
      ...vault,
      version: 33,
      registryHistory: [packet.firstBundle],
      userAuthority: {
        signedTransition: packet.signedTransition,
        registryStart: nextHead,
        registry: nextHead,
        archive,
        sourcesDigest: await h.core.sha(h.core.canonical([])),
        sources: [],
      },
    };
    session.lock();

    const pages = [];
    const packets = [];
    const bridge = db.client(uid, storage, {
      async readOriginalRegistryPage(request, signal) {
        assert.equal(signal.aborted, false);
        assert.deepEqual(request.target, previousHead);
        assert.deepEqual(await storage.get(pinKey), before);
        const position = request.base.registrySequence;
        const bundles = original.registryHistory.slice(position, position + 4);
        const response = { ...request, rootKeyId: vault.rootKeyId, bundles };
        pages.push(position);
        packets.push(Buffer.byteLength(JSON.stringify(response)));
        return response;
      },
    });
    assert.equal((await bridge.unlock(fresh, material())).needsDeviceRegistration, false);
    assert.deepEqual(pages, [1, 5, 9, 13, 17, 21, 25, 29]);
    assert.ok(Math.max(...packets) < 131_072);
    await bridge.acceptVault(fresh);
    assert.equal((await storage.get(pinKey)).registrySequence, 33);
    assert.equal(pages.length, 8);
    bridge.lock();

    const cold = db.client(uid, storage, { readOriginalRegistryPage: noPage });
    assert.equal((await cold.unlock(fresh, material())).needsDeviceRegistration, false);
    cold.lock();
    const stale = db.client(uid, storage, { readOriginalRegistryPage: noPage });
    await assert.rejects(stale.unlock(original, material()), /rollback_detected/);
  });
});

test("the current Worker verifies original archive lifecycle controls against the signed prior chain", async () => {
  await browser.withDatabase(async (db) => {
    const { uid, h, material, vault, state, storage } = await initialize(db);
    const owner = vault.archive.ownerSubject;
    const core = new h.core.VaultCore(uid, () => 1000);
    const record = await storage.get(owner + ":device:" + vault.vaultId);
    await core.unlock(vault, material(), { device: record.device });
    const { FlattenedSign } = await import("jose");
    const history = [];
    for (const [index, action] of ["recovery_authorize", "recovery_revoke"].entries()) {
      const issuedAt = 900 + index;
      const stableOperationId = "synthetic_old_archive_history_0" + index;
      const payload = {
        contractVersion: state.contractVersion,
        profile: state.profile,
        ownerSubject: owner,
        vaultId: vault.vaultId,
        rootKeyId: vault.rootKeyId,
        action,
        stableOperationId,
        expectedVaultVersion: vault.version,
        expectedLifecycleVersion: index,
        expectedArchiveRevision: 0,
        expectedArchiveDigest: state.archiveDigest,
        registrySequence: state.registrySequence,
        checkpointDigest: state.checkpointDigest,
        keyEpoch: state.keyEpoch,
        issuedAt,
        expiresAt: 950 + index,
        authorizationId: "synthetic_recovery_authorization",
        ...(index === 0 ? { newArchiveDigest: "b".repeat(64) } : {}),
      };
      const command = await new FlattenedSign(new TextEncoder().encode(h.core.canonical(payload)))
        .setProtectedHeader({
          alg: "ES256",
          kid: vault.rootKeyId,
          typ: "fv-control+jws",
          cty: "application/json",
        })
        .sign(core.root);
      history.push({
        command,
        receipt: {
          profile: state.profile,
          ownerSubject: owner,
          vaultId: vault.vaultId,
          rootKeyId: vault.rootKeyId,
          operationId: stableOperationId,
          action,
          lifecycleVersion: index + 1,
          archiveRevision: 0,
          archiveDigest: state.archiveDigest,
          commandFingerprint: await h.core.signingFingerprint(command),
          acceptedAt: issuedAt,
        },
      });
    }
    const previous = { ...state, history, lifecycleVersion: 2 };
    await core.verifyLifecycle(vault, previous);
    const packet = await signedTransition(h, uid, vault, previous, material, core);
    const { nextHead, archive } = decoded(packet.signedTransition);
    const current = {
      ...vault,
      version: vault.version + 1,
      registryHistory: [packet.firstBundle],
      userAuthority: {
        signedTransition: packet.signedTransition,
        registryStart: nextHead,
        registry: nextHead,
        archive,
        sourcesDigest: await h.core.sha(h.core.canonical([])),
        sources: [],
      },
    };
    const result = {
      ...previous,
      vaultVersion: current.version,
      registrySequence: nextHead.registrySequence,
      checkpointDigest: nextHead.checkpointDigest,
      originalCheckpoints: [vault.registryHistory[0].checkpoint],
    };
    const reader = new h.core.VaultCore(uid, () => 1000);
    await reader.unlockForResults(current, material());
    assert.equal((await reader.verifyLifecycle(current, result)).lifecycleVersion, 2);
    await assert.rejects(
      reader.verifyLifecycle(current, { ...result, originalCheckpoints: [] }),
      /untrusted_lifecycle/,
    );
  });
});

test("a cold User vault verifies a new Passkey against its signed archive continuation", async () => {
  await browser.withDatabase(async (db) => {
    const { session, uid, h, material, vault, state } = await initialize(db);
    await session.verifyLifecycle(vault, state);
    const handover = await signedTransition(h, uid, vault, state, material);
    const { nextHead, archive } = decoded(handover.signedTransition);
    const original = {
      ...vault,
      version: vault.version + 1,
      registryHistory: [handover.firstBundle],
      userAuthority: {
        signedTransition: handover.signedTransition,
        registryStart: nextHead,
        registry: nextHead,
        archive,
        sources: [],
        sourcesDigest: await h.core.sha(h.core.canonical([])),
      },
    };
    const lifecycle = await lifecycleState(h, { vault: original });
    const secret = new Uint8Array(32).fill(17);
    const updatedMaterial = () => ({
      credentialId: h.core.b64(new Uint8Array(32).fill(18)),
      prfSalt: h.core.b64(new Uint8Array(32).fill(19)),
      secret: secret.slice().buffer,
    });
    const writer = new h.core.VaultCore(uid, () => 1000);
    await writer.unlock(original, material());
    const { packet } = await writer.prepareArchiveChange(
      original,
      lifecycle,
      updatedMaterial(),
      "passkey_change",
    );
    const command = decoded(packet.command);
    const receipt = {
      profile: lifecycle.profile,
      ownerSubject: vault.archive.ownerSubject,
      vaultId: vault.vaultId,
      rootKeyId: vault.rootKeyId,
      operationId: packet.operationId,
      action: "archive_replace",
      lifecycleVersion: 1,
      archiveRevision: 1,
      archiveDigest: command.newArchiveDigest,
      commandFingerprint: await h.core.signingFingerprint(packet.command),
      acceptedAt: 1000,
    };
    const changed = {
      ...lifecycle,
      archive: packet.archive,
      archiveDigest: command.newArchiveDigest,
      archiveRevision: 1,
      lifecycleVersion: 1,
      history: [{ command: packet.command, receipt }],
    };
    const current = {
      ...original,
      archive: packet.archive,
      userAuthority: {
        ...original.userAuthority,
        archive: { state: "active", version: 2, digest: command.newArchiveDigest },
        archiveLifecycle: { state: changed, originalCheckpoints: [] },
      },
    };
    const reader = new h.core.VaultCore(uid, () => 1000);
    await reader.unlockForResults(current, updatedMaterial());
    assert.equal(
      (await reader.verifyLifecycle(current, { ...changed, originalCheckpoints: [] }))
        .archiveDigest,
      command.newArchiveDigest,
    );
    await assert.rejects(reader.verifyLifecycle(original, lifecycle), /rollback_detected/);
    const currentProof = current.userAuthority;
    const withoutHistory = structuredClone(current);
    delete withoutHistory.userAuthority.archiveLifecycle;
    await assert.rejects(
      new h.core.VaultCore(uid, () => 1000).unlockForResults(withoutHistory, updatedMaterial()),
      /registry_conflict/,
    );
    const altered = structuredClone(current);
    altered.userAuthority.archiveLifecycle.state.history[0].receipt.archiveRevision = 2;
    await assert.rejects(
      new h.core.VaultCore(uid, () => 1000).unlockForResults(altered, updatedMaterial()),
      /untrusted_lifecycle/,
    );
    assert.equal(currentProof.archiveLifecycle.state.history[0].receipt.archiveRevision, 1);
  });
});

test("a transferred vault shows deletion only after its exact signed removal and supports recovery", async () => {
  await browser.withDatabase(async (db) => {
    const { session, uid, h, material, vault, state } = await initialize(db);
    await session.verifyLifecycle(vault, state);
    const handover = await signedTransition(h, uid, vault, state, material);
    const { nextHead, archive } = decoded(handover.signedTransition);
    const original = {
      ...vault,
      version: vault.version + 1,
      registryHistory: [handover.firstBundle],
      userAuthority: {
        signedTransition: handover.signedTransition,
        registryStart: nextHead,
        registry: nextHead,
        archive,
        sources: [],
        sourcesDigest: await h.core.sha(h.core.canonical([])),
      },
    };
    const stateAfterHandover = await lifecycleState(h, { vault: original });
    const rootOwner = new h.core.VaultCore(uid, () => 1000);
    await rootOwner.unlock(original, material());
    const kit = await rootOwner.createRecoveryKit(original, stateAfterHandover);
    const { packet, record } = await rootOwner.prepareArchiveDeletion(original, stateAfterHandover);
    const command = packet.body.command;
    const digest = await h.core.sha(h.core.canonical(null));
    const receipt = {
      profile: stateAfterHandover.profile,
      ownerSubject: original.archive.ownerSubject,
      vaultId: original.vaultId,
      rootKeyId: original.rootKeyId,
      operationId: packet.operationId,
      action: "archive_delete",
      lifecycleVersion: 1,
      archiveRevision: 1,
      archiveDigest: digest,
      commandFingerprint: await h.core.signingFingerprint(command),
      acceptedAt: 1000,
    };
    const deletedState = {
      ...stateAfterHandover,
      archive: null,
      archiveDigest: digest,
      lifecycleVersion: 1,
      archiveRevision: 1,
      history: [{ command, receipt }],
    };
    const deleted = {
      ...original,
      archive: null,
      userAuthority: {
        ...original.userAuthority,
        archive: { state: "deleted", version: 2, digest },
        archiveLifecycle: { state: deletedState, originalCheckpoints: [] },
      },
    };
    const fresh = new h.core.VaultCore(uid, () => 1000);
    await assert.rejects(fresh.unlock(deleted, material()), /archive_deleted/);
    assert.equal(
      (await fresh.inspectArchiveDeletion(deleted, deletedState, record)).outcome,
      "deleted",
    );
    await fresh.importRecoveryKit(deleted, deletedState, kit.file, kit.code);

    const incomplete = structuredClone(deleted);
    delete incomplete.userAuthority.archiveLifecycle;
    await assert.rejects(
      new h.core.VaultCore(uid, () => 1000).verifyLifecycle(incomplete, deletedState),
      /registry_conflict/,
    );
    const foreign = structuredClone(deleted);
    foreign.userAuthority.archiveLifecycle.state.history[0].receipt.operationId =
      "foreign_synthetic_operation";
    await assert.rejects(
      new h.core.VaultCore(uid, () => 1000).verifyLifecycle(foreign, deletedState),
      /untrusted_lifecycle/,
    );
  });
});

test("a verified User head clears a locally pending receipt from the retired handover", async () => {
  await browser.withDatabase(async (db) => {
    const { session, storage, state, uid, vault, material, h } = await initialize(db);
    const packet = await signedTransition(h, uid, vault, state, material);
    const owner = vault.archive.ownerSubject;
    const key = owner + ":user-handover:" + vault.vaultId;
    const row = {
      ownerSubject: owner,
      vaultId: vault.vaultId,
      rootKeyId: vault.rootKeyId,
      pending: packet,
    };
    assert.equal(await storage.insert(key, row), true);
    session.lock();

    const reload = db.client(uid, storage);
    assert.deepEqual(await storage.get(key), row);
    const transition = decoded(packet.signedTransition);
    const current = {
      ...vault,
      version: transition.nextVaultVersion,
      registryHistory: [packet.firstBundle],
      userAuthority: {
        signedTransition: packet.signedTransition,
        registry: transition.nextHead,
        registryStart: transition.nextHead,
        archive: transition.archive,
        sourcesDigest: await h.core.sha(h.core.canonical([])),
        sources: [],
      },
    };
    assert.equal((await reload.unlock(current, material())).needsDeviceRegistration, false);
    await reload.acceptVault(current);
    assert.equal(await storage.get(key), null);
  });
});

test("Worker verifies the fresh User epoch against the original pinned Root, archive and nonce", async () => {
  await browser.withDatabase(async (db) => {
    const { session, state, vault, storage, evidence, material, uid, h } = await initialize(db);
    await session.verifyLifecycle(vault, state);
    const key = vault.archive.ownerSubject + ":pin";
    const pinned = await storage.get(key);
    const packet = await signedTransition(h, uid, vault, state, material);
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
