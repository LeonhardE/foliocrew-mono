const test = require("node:test"),
  assert = require("node:assert/strict");
const { webcrypto } = require("node:crypto");
const { fixture, contract, C } = require("./resource-display-fixtures.cjs");
const { compile, deferred } = require("./resource-library-helpers.cjs");
test("actual accepted Owner checkpoint yields the independent Worker scope and verifies sealed alias crypto", async () => {
  const f = await fixture();
  try {
    const ctx = f.state.proof.context(() => f.state);
    assert.ok(ctx);
    const body = ctx.read(f.body());
    assert.deepEqual(JSON.parse(JSON.stringify(body.scope)), f.scope);
    assert.equal(
      (
        await f.owner.session.openDisplayNames({
          refs: f.state.sources.map((s) => s.resourceRef),
          items: body.displayNames.items,
        })
      )[0].name,
      "Synthetic alias",
    );
    assert.ok(!JSON.stringify(body).includes("Synthetic alias"));
    assert.ok(Buffer.byteLength(ctx.coalesceScope) < 8192);
  } finally {
    await f.close();
  }
});
test("every one of the seven scope fields, unknown envelope keys and corrupt other components fail before extraction", async () => {
  const f = await fixture();
  try {
    const ctx = f.state.proof.context(() => f.state);
    for (const [field, patch] of Object.entries({
      ownerSubject: "b".repeat(64),
      vaultId: "foreign",
      rootKeyId: "B".repeat(43),
      version: 2,
      registrySequence: 2,
      checkpointDigest: "b".repeat(64),
      keyEpoch: 2,
    })) {
      const v = f.body();
      v.scope[field] = patch;
      assert.throws(() => ctx.read(v), /invalid_response/, field);
    }
    for (const mutate of [
      (v) => (v.extra = true),
      (v) => (v.displayNameCapabilities.extra = true),
      (v) => (v.displayNames.items[0].state.rootKeyId = "B".repeat(43)),
      (v) => v.displayNames.items.push(v.displayNames.items[0]),
      (v) => (v.displayNames.items[0].command.privateKey = "bad"),
      (v) => (v.catalogue.groups[0].items[0].state = "invented"),
      (v) => (v.scope.registrySequence = 33),
    ]) {
      const v = f.body();
      mutate(v);
      assert.throws(() => ctx.read(v), /invalid_response/);
    }
    const hint = {
      contractVersion: C,
      profile: "folioview.owner-resource-display.v1",
      mode: "separate",
      reason: "aggregate_too_large",
    };
    assert.equal(ctx.read(hint).mode, "separate");
    for (const extra of [
      { ...hint, catalogue: null },
      { ...hint, reason: "unsupported" },
    ])
      assert.throws(() => ctx.read(extra));
  } finally {
    await f.close();
  }
});
test("private context is fenced by Owner, UID, session, generation, public nested mutation and complete ref epochs", async () => {
  const f = await fixture();
  try {
    const ctx = f.state.proof.context(() => f.state),
      old = { ...f.state };
    for (const patch of [
      { owner: "b:2" },
      { uid: "b" },
      { session: {} },
      { generation: 2 },
      { eligible: false },
      { vault: structuredClone(f.state.vault) },
      { sources: [{ ...f.state.sources[0], sourceEpoch: 2 }] },
    ]) {
      Object.assign(f.state, patch);
      assert.throws(() => ctx.assertCurrent(), /cancelled/);
      Object.assign(f.state, old);
    }
    const before = f.state.vault.registryHistory[0].checkpoint.signature;
    f.state.vault.registryHistory[0].checkpoint.signature = "changed";
    assert.throws(() => ctx.assertCurrent(), /cancelled/);
    f.state.vault.registryHistory[0].checkpoint.signature = before;
    assert.doesNotThrow(() => ctx.assertCurrent());
    const received = ctx.read(f.body());
    received.scope.ownerSubject = "changed";
    received.displayNames.items[0].state.ref.incarnation = "changed";
    assert.doesNotThrow(() => ctx.read(f.body()));
  } finally {
    await f.close();
  }
});
test("equivalent existing reaccept preserves a same-context in-flight lease while an unaccepted replacement does not", async () => {
  const f = await fixture();
  try {
    const old = f.state.proof.context(() => f.state);
    const snapshot = contract.resourceDisplaySnapshot(f.state.vault),
      next = snapshot.vault;
    await f.owner.session.acceptVault(next);
    const proof = await contract.verifiedDisplayVault(
      snapshot,
      f.state.sources,
      f.state.owner,
      f.state.uid,
      1,
      f.state.session,
    );
    f.state.vault = next;
    f.state.proof = proof;
    assert.doesNotThrow(() => old.assertCurrent());
    assert.equal(proof.context(() => f.state).coalesceScope, old.coalesceScope);
    f.state.vault = structuredClone(next);
    assert.throws(() => old.assertCurrent(), /cancelled/);
  } finally {
    await f.close();
  }
});
test("optional derivation failures never throw and async external mutation cannot poison a prepared context", async () => {
  const f = await fixture();
  try {
    const gate = deferred(),
      started = deferred();
    let calls = 0;
    const module = compile(
      "../lib/resource-display.ts",
      {},
      {
        crypto: {
          subtle: {
            digest: async (...args) => {
              calls++;
              started.resolve();
              await gate.promise;
              return webcrypto.subtle.digest(...args);
            },
          },
        },
      },
    );
    const original = structuredClone(f.state.vault);
    const snapshot = module.resourceDisplaySnapshot(f.state.vault);
    await f.owner.session.acceptVault(snapshot.vault);
    f.state.vault = snapshot.vault;
    const pending = module.verifiedDisplayVault(
      snapshot,
      f.state.sources,
      f.state.owner,
      f.state.uid,
      1,
      f.state.session,
    );
    await started.promise;
    f.state.vault.registryHistory[0].checkpoint.payload = "e30";
    gate.resolve();
    const proof = await pending;
    assert.equal(calls, 2);
    assert.equal(proof, null);
    Object.assign(f.state.vault, original);
    const recovered = await module.verifiedDisplayVault(
      snapshot,
      f.state.sources,
      f.state.owner,
      f.state.uid,
      1,
      f.state.session,
    );
    f.state.proof = recovered;
    assert.equal(
      recovered.context(() => f.state).read(f.body()).scope.checkpointDigest,
      f.scope.checkpointDigest,
    );
    const broken = compile(
      "../lib/resource-display.ts",
      {},
      {
        crypto: {
          subtle: {
            digest: async () => {
              throw Error("unsupported");
            },
          },
        },
      },
    );
    assert.equal(
      await broken.verifiedDisplayVault(
        snapshot,
        f.state.sources,
        f.state.owner,
        f.state.uid,
        1,
        f.state.session,
      ),
      null,
    );
    assert.equal(
      await contract.verifiedDisplayVault(
        snapshot,
        f.state.sources,
        f.state.owner,
        "other",
        1,
        f.state.session,
      ),
      null,
    );
  } finally {
    await f.close();
  }
});
test("a legal 32-generation actual Worker history and maximal fixed context fields fit the unchanged optimization bounds", async () => {
  const f = await fixture();
  try {
    const vault = structuredClone(f.state.vault);
    for (let n = 2; n <= 32; n++) {
      const previous = JSON.parse(
        Buffer.from(vault.registryHistory.at(-1).checkpoint.payload, "base64url"),
      );
      const next = {
        ...previous,
        registrySequence: n,
        previousDigest: await f.runtime.core.sha(f.runtime.core.canonical(previous)),
        issuedAt: 1000 + n,
      };
      vault.registryHistory.push({
        ...structuredClone(vault.registryHistory[0]),
        checkpoint: await new f.runtime.jose.FlattenedSign(
          new TextEncoder().encode(f.runtime.core.canonical(next)),
        )
          .setProtectedHeader({
            alg: "ES256",
            typ: "fv-control+jws",
            kid: vault.rootKeyId,
            cty: "application/json",
          })
          .sign(f.owner.session.root),
      });
    }
    vault.version = 32;
    f.owner.time(1100);
    await f.owner.session.acceptVault(vault);
    const snapshot = contract.resourceDisplaySnapshot(vault);
    await f.owner.session.acceptVault(snapshot.vault);
    const proof = await contract.verifiedDisplayVault(
      snapshot,
      f.state.sources,
      f.state.owner,
      f.state.uid,
      1,
      f.state.session,
    );
    assert.ok(proof);
    Object.assign(f.state, { vault: snapshot.vault, proof });
    assert.equal(
      proof
        .context(() => f.state)
        .read({
          ...f.body(),
          scope: {
            ...f.scope,
            version: 32,
            registrySequence: 32,
            checkpointDigest: await f.runtime.core.sha(
              f.runtime.core.canonical(
                JSON.parse(
                  Buffer.from(vault.registryHistory.at(-1).checkpoint.payload, "base64url"),
                ),
              ),
            ),
          },
        }).scope.registrySequence,
      32,
    );
    const max = {
      ...f.scope,
      vaultId: "v".repeat(128),
      version: Number.MAX_SAFE_INTEGER,
      registrySequence: 32,
      keyEpoch: Number.MAX_SAFE_INTEGER,
    };
    const refs = Array.from({ length: 10 }, (_, i) => ({
      resourceRef: {
        kind: "holdings",
        sourceService: "portfolio",
        resourceId: String(i) + "r".repeat(127),
        incarnation: "i".repeat(128),
      },
      sourceEpoch: Number.MAX_SAFE_INTEGER,
    }));
    assert.ok(Buffer.byteLength(JSON.stringify([max, Number.MAX_SAFE_INTEGER, refs])) <= 8192);
  } finally {
    await f.close();
  }
});

test("the unchanged12288-byte command ceiling admits maximum-length actual names and the transport boundary", async () => {
  const f = await fixture();
  try {
    const name = "😀".repeat(80),
      prepared = await f.owner.session.prepareDisplayName({
        ref: f.state.sources[0].resourceRef,
        item: null,
        name,
      }),
      command = prepared.body.command,
      payload = JSON.parse(Buffer.from(command.payload, "base64url"));
    const item = {
      command,
      state: {
        ...f.item.state,
        revision: payload.revision,
        stableOperationId: payload.stableOperationId,
        recipientKeyId: payload.recipientKeyId,
        operationFingerprint: require("node:crypto")
          .createHash("sha256")
          .update(command.protected + "." + command.payload)
          .digest("hex"),
      },
    };
    const body = f.body();
    body.displayNames.items = [item];
    const read = f.state.proof.context(() => f.state).read(body);
    assert.equal(
      (
        await f.owner.session.openDisplayNames({
          refs: f.state.sources.map((s) => s.resourceRef),
          items: read.displayNames.items,
        })
      )[0].name,
      name,
    );
    assert.equal(Buffer.byteLength(name), 320);
    assert.ok(Buffer.byteLength(JSON.stringify(command)) <= 12288);
    // This second part proves the wire ceiling only; dummy base64 is deliberately not a valid signed command.
    const edge = { protected: "e30", payload: "A", signature: "A".repeat(86) };
    edge.payload = "A".repeat(12288 - Buffer.byteLength(JSON.stringify(edge)) + 1);
    assert.equal(Buffer.byteLength(JSON.stringify(edge)), 12288);
    const boundary = f.body();
    boundary.displayNames.items[0].command = edge;
    assert.equal(contract.readResourceDisplay(boundary).mode, "full");
    edge.payload += "A";
    assert.throws(() => contract.readResourceDisplay(boundary), /invalid_response/);
    const page = f.body();
    page.scope.vaultId = "v".repeat(128);
    page.displayNames.items = Array.from({ length: 10 }, (_, i) => ({
      command: { ...edge, payload: edge.payload.slice(1) },
      state: {
        ...f.item.state,
        vaultId: page.scope.vaultId,
        revision: Number.MAX_SAFE_INTEGER,
        acceptedAt: Number.MAX_SAFE_INTEGER,
        stableOperationId: "o".repeat(128),
        ref: {
          kind: "holdings",
          sourceService: "portfolio",
          resourceId: String(i) + "r".repeat(127),
          incarnation: "i".repeat(128),
        },
      },
    }));
    assert.equal(contract.readResourceDisplay(page).mode, "full");
    assert.ok(
      Buffer.byteLength(JSON.stringify(page.displayNames)) < 262144,
      "Ten maximally sized transport rows remain below the original listing bound",
    );
  } finally {
    await f.close();
  }
});
