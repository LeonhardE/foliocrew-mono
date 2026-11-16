const test = require("node:test"),
  assert = require("node:assert/strict");
const { hooks } = require("./resource-ui-harness.cjs"),
  { compile, response, settle, deferred, ref } = require("./resource-library-helpers.cjs");
const C = "folioview.agent-workspace.v2.0",
  P = "folioview.private-display-name.v1";
const wrap = (data) => ({ contractVersion: C, profile: P, ...data });
function harness(transport) {
  const h = hooks(),
    calls = [],
    events = new Map(),
    packets = new Map();
  let owner = "A",
    now = 100000,
    active = true,
    configured = true,
    visible = true,
    locked = false,
    names = [{ state: { ref: ref("holdings", "source_synthetic") }, name: "FIRST" }],
    head = { name: "LATEST" };
  const r = ref("holdings", "source_synthetic");
  const overrides = {};
  const workspace = () => ({
    owner,
    phase: locked ? "locked" : "unlocked",
    canWriteState: true,
    vault: { vaultId: "vault", rootKeyId: "root" },
    vaultGeneration: 1,
    sources: [{ resourceRef: r, sourceEpoch: 1 }],
    async refreshVault() {
      calls.push({ root: true });
    },
    async openDisplayNames(refs, items) {
      return items.map((item) => ({ ref: item.state.ref, name: item.name, state: item.state }));
    },
    async openDisplayName(ref, item) {
      return { ref, name: item?.name, state: item?.state };
    },
    async loadDisplayNamePending() {
      return packets.get(owner) ?? null;
    },
    async prepareDisplayName({ ref, name }) {
      const packet = { ref, operationId: "op", body: { CIPHERTEXT: true } };
      packets.set(owner, packet);
      calls.push({ prepared: name });
      return packet;
    },
    async discardDisplayNamePending(_ref, operationId) {
      assert.equal(packets.get(owner)?.operationId, operationId);
      packets.delete(owner);
      calls.push({ discarded: operationId });
    },
    async finishDisplayNamePending(_ref, value) {
      assert.equal(value.item.state.stableOperationId, "op");
      packets.delete(owner);
    },
    ...overrides,
  });
  const { useDisplayNames } = compile(
    "../components/useDisplayNames.ts",
    {
      react: h.react,
      "./AuthProvider": {
        useAuth: () => ({
          status: "authenticated",
          agentHubConfigured: configured,
          sessionKey: owner,
          requestPrivate: async (service, path, key, options) => {
            const call = { service, path, key, options };
            calls.push(call);
            const custom = transport && (await transport(call));
            if (custom !== undefined) return custom;
            if (path.endsWith("capabilities"))
              return response(wrap({ enabled: true, maxSources: 10, maxNameLength: 80 }));
            if (path.endsWith("commands") || path.includes("operations/"))
              return response(
                wrap({ item: { name: "ORIGINAL", state: { stableOperationId: "op" } } }),
              );
            if (path.endsWith("/holdings")) return response(wrap({ items: names }));
            return response(wrap({ item: head }));
          },
        }),
      },
    },
    {
      document: {
        get visibilityState() {
          return visible ? "visible" : "hidden";
        },
        addEventListener: (k, v) => events.set(k, v),
        removeEventListener: (k) => events.delete(k),
      },
      setTimeout,
      clearTimeout,
      Object,
      JSON,
      Date: class extends Date {
        static now() {
          return now;
        }
      },
    },
  );
  const render = () => h.render(() => useDisplayNames(workspace(), active));
  return {
    render,
    calls,
    packets,
    r,
    close: h.close,
    active: (v) => (active = v),
    owner: (v) => (owner = v),
    capability: (v) => (configured = v),
    lock: (v) => (locked = v),
    visibility(v) {
      visible = v;
      events.get("visibilitychange")?.();
    },
    head: (v) => (head = v),
    workspace: (patch) => Object.assign(overrides, patch),
    advance: (ms) => (now += ms),
    async ready() {
      render();
      for (let i = 0; i < 8; i++) {
        await settle();
        render();
      }
      return render();
    },
  };
}
test("names load once across navigation, remain scoped to unlocked visible Owner, and never auto-submit", async () => {
  const h = harness();
  try {
    let m = await h.ready();
    assert.equal(m.name(h.r), "FIRST");
    const reads = h.calls.length;
    h.active(false);
    h.render();
    h.active(true);
    await h.ready();
    assert.equal(h.calls.length, reads);
    h.visibility(false);
    assert.equal(h.render().name(h.r), null);
    h.visibility(true);
    await h.ready();
    h.owner("B");
    assert.equal(h.render().name(h.r), null);
    await h.ready();
    assert.ok(h.calls.filter((c) => c.key === "B").length);
    h.lock(true);
    assert.equal(h.render().name(h.r), null);
    assert.equal(h.calls.filter((c) => c.options?.method === "POST").length, 0);
  } finally {
    h.close();
  }
});

test("leaving during capabilities aborts only the automatic name read and cannot start listing after a late reply", async () => {
  const gate = deferred();
  let held = true;
  const h = harness((call) =>
    held && call.path.endsWith("capabilities") ? gate.promise : undefined,
  );
  try {
    h.render();
    await settle();
    const first = h.calls[0];
    h.active(false);
    h.render();
    assert.equal(first.options.signal.aborted, true);
    gate.resolve(response(wrap({ enabled: true, maxSources: 10, maxNameLength: 80 })));
    await settle();
    assert.equal(h.calls.filter((c) => c.path?.endsWith("/holdings")).length, 0);
    assert.equal(h.render().loading, false);
    assert.equal(h.render().error, "");
    held = false;
    h.active(true);
    assert.equal((await h.ready()).name(h.r), "FIRST");
    const reads = h.calls.length;
    h.active(false);
    h.render();
    h.active(true);
    await h.ready();
    assert.equal(h.calls.length, reads, "Completed same-scope names retain their30s freshness");
    h.active(false);
    h.render();
    h.advance(30000);
    h.active(true);
    await h.ready();
    assert.equal(h.calls.length, reads + 2);
  } finally {
    h.close();
  }
});

test("leaving during listing stops Worker dispatch even when transport ignores its abort", async () => {
  const gate = deferred();
  let opened = 0;
  const h = harness((call) => (call.path.endsWith("/holdings") ? gate.promise : undefined));
  h.workspace({
    async openDisplayNames() {
      opened++;
      return [];
    },
  });
  try {
    h.render();
    await settle();
    const listing = h.calls.find((c) => c.path?.endsWith("/holdings"));
    assert.ok(listing);
    h.active(false);
    h.render();
    assert.equal(listing.options.signal.aborted, true);
    gate.resolve(response(wrap({ items: [] })));
    await settle();
    assert.equal(opened, 0);
    assert.equal(h.render().ready, false);
  } finally {
    h.close();
  }
});

test("a late Worker name result cannot publish or begin local pending reads after leaving", async () => {
  const gate = deferred();
  let pendingReads = 0,
    opened = 0;
  const h = harness();
  h.workspace({
    async openDisplayNames(refs, items) {
      opened++;
      await gate.promise;
      return items.map((i) => ({ ref: i.state.ref, name: i.name, state: i.state }));
    },
    async loadDisplayNamePending() {
      pendingReads++;
      return null;
    },
  });
  try {
    h.render();
    await settle();
    assert.equal(opened, 1);
    h.active(false);
    h.render();
    gate.resolve();
    await settle();
    assert.equal(pendingReads, 0);
    assert.equal(h.render().name(h.r), null);
    assert.equal(h.render().ready, false);
    assert.equal(h.render().error, "");
  } finally {
    h.close();
  }
});

test("leaving between local pending reads stops the next source without discarding its original packet", async () => {
  const gate = deferred(),
    h = harness(),
    seen = [];
  const other = ref("holdings", "source_second");
  const original = { operationId: "original", body: { CIPHERTEXT: true } };
  h.packets.set("A", original);
  h.workspace({
    sources: [
      { resourceRef: h.r, sourceEpoch: 1 },
      { resourceRef: other, sourceEpoch: 1 },
    ],
    async loadDisplayNamePending(r) {
      seen.push(r.resourceId);
      await gate.promise;
      return original;
    },
  });
  try {
    h.render();
    await settle();
    assert.deepEqual(seen, [h.r.resourceId]);
    h.active(false);
    h.render();
    gate.resolve();
    await settle();
    assert.deepEqual(seen, [h.r.resourceId]);
    assert.equal(h.packets.get("A"), original);
  } finally {
    h.close();
  }
});

test("automatic-read navigation cancellation does not abort an explicit rename or replace an unknown-ACK packet", async () => {
  const ack = deferred();
  const h = harness((call) => (call.path.endsWith("commands") ? ack.promise : undefined));
  try {
    await h.ready();
    const write = h.render().rename(h.r, "NEW");
    await settle();
    const command = h.calls.find((c) => c.path?.endsWith("commands"));
    assert.ok(command);
    const original = h.packets.get("A");
    h.active(false);
    h.render();
    assert.equal(command.options.signal.aborted, false);
    ack.resolve(response({}, 503));
    assert.equal(await write, false);
    assert.equal(h.packets.get("A"), original);
    assert.equal(h.calls.filter((c) => c.options?.method === "POST").length, 1);
  } finally {
    h.close();
  }
});

test("rapid leave and return cannot let the old read clear the new loading state or extend its cache", async () => {
  const first = deferred(),
    second = deferred();
  let count = 0;
  const h = harness((call) =>
    call.path.endsWith("capabilities")
      ? ++count === 1
        ? first.promise
        : count === 2
          ? second.promise
          : undefined
      : undefined,
  );
  try {
    h.render();
    await settle();
    h.active(false);
    h.render();
    h.active(true);
    h.render();
    await settle();
    assert.equal(count, 2);
    assert.equal(h.render().loading, true);
    first.resolve(response(wrap({ enabled: true, maxSources: 10, maxNameLength: 80 })));
    await settle();
    assert.equal(h.render().loading, true);
    assert.equal(h.render().ready, false);
    second.resolve(response(wrap({ enabled: true, maxSources: 10, maxNameLength: 80 })));
    assert.equal((await h.ready()).name(h.r), "FIRST");
    h.active(false);
    h.render();
    h.advance(30000);
    h.active(true);
    await h.ready();
    assert.equal(count, 3);
  } finally {
    h.close();
  }
});
test("leaving during an explicit fresh Root read aborts its read lane before capabilities without touching pending packets", async () => {
  const gate = deferred(),
    h = harness();
  let signal;
  try {
    await h.ready();
    const original = { operationId: "original", body: { CIPHERTEXT: true } };
    h.packets.set("A", original);
    h.workspace({
      async refreshVault(s) {
        signal = s;
        await gate.promise;
      },
    });
    const before = h.calls.length,
      read = h.render().reload();
    await settle();
    assert.ok(signal);
    h.active(false);
    h.render();
    assert.equal(signal.aborted, true);
    gate.resolve();
    await read;
    await settle();
    assert.equal(h.calls.length, before);
    assert.equal(h.packets.get("A"), original);
    assert.equal(h.render().error, "");
  } finally {
    h.close();
  }
});
test("changed vault versions and source epochs cancel the old read and start a fresh bounded name read", async () => {
  const old = deferred();
  let caps = 0;
  const h = harness((call) =>
    call.path.endsWith("capabilities") && ++caps === 1 ? old.promise : undefined,
  );
  h.workspace({ vault: { vaultId: "vault", rootKeyId: "root", version: 1 } });
  try {
    h.render();
    await settle();
    const first = h.calls[0];
    h.workspace({ vault: { vaultId: "vault", rootKeyId: "root", version: 2 } });
    h.render();
    await settle();
    assert.equal(first.options.signal.aborted, true);
    assert.equal((await h.ready()).name(h.r), "FIRST");
    assert.equal(caps, 2);
    old.resolve(response(wrap({ enabled: true, maxSources: 10, maxNameLength: 80 })));
    await settle();
    h.workspace({ sources: [{ resourceRef: h.r, sourceEpoch: 2 }] });
    await h.ready();
    assert.equal(caps, 3);
    assert.equal(h.calls.filter((c) => c.path?.endsWith("/holdings")).length, 2);
  } finally {
    h.close();
  }
});
test("unknown save keeps the original packet; explicit recovery labels from latest head instead of old original receipt", async () => {
  let reject = true;
  const h = harness((call) => {
    if (call.path.endsWith("commands") && reject) throw Error("lost response");
  });
  try {
    let m = await h.ready();
    assert.equal(await m.rename(h.r, "NEW"), false);
    m = h.render();
    assert.equal(m.pending(h.r), true);
    const packet = h.packets.get("A");
    assert.equal(await m.rename(h.r, "OTHER"), false);
    assert.equal(h.packets.get("A"), packet);
    reject = false;
    assert.equal(await h.render().recover(h.r), true);
    m = h.render();
    assert.equal(m.name(h.r), "LATEST");
    assert.equal(m.pending(h.r), false);
    assert.equal(h.calls.filter((c) => c.options?.method === "POST").length, 1);
    assert.equal(h.calls.filter((c) => c.prepared).length, 1);
  } finally {
    h.close();
  }
});
test("late reads cannot overwrite a completed rename or escape an account change", async () => {
  const gate = deferred();
  let delay = false;
  const h = harness((call) =>
    delay && call.path.endsWith("/holdings") ? gate.promise : undefined,
  );
  try {
    await h.ready();
    delay = true;
    const old = h.render().reload();
    await settle();
    const renamed = h.render().rename(h.r, "NEW");
    await renamed;
    gate.resolve(response(wrap({ items: [{ name: "STALE", state: { ref: h.r } }] })));
    await old;
    assert.equal(h.render().name(h.r), "LATEST");
    delay = false;
    h.owner("B");
    assert.equal(h.render().name(h.r), null);
  } finally {
    h.close();
  }
});
test("closed response contracts and missing capability prevent names without breaking holdings", async () => {
  const h = harness((call) =>
    call.path.endsWith("capabilities")
      ? response(wrap({ enabled: true, maxSources: 10, maxNameLength: 80, plaintext: "BAD" }))
      : undefined,
  );
  try {
    const m = await h.ready();
    assert.equal(m.error, "invalid_response");
    assert.equal(m.enabled, false);
    h.capability(false);
    const before = h.calls.length;
    await h.ready();
    assert.equal(h.calls.length, before);
    assert.equal(h.render().scope, null);
  } finally {
    h.close();
  }
});

test("explicit local recovery checks original result first, clears only that packet, and reads current without a POST", async () => {
  const h = harness((call) => {
    if (call.path.endsWith("commands")) throw Error("lost");
    if (call.path.includes("/operations/")) return response({}, 404);
  });
  try {
    await h.ready();
    await h.render().rename(h.r, "Unknown");
    assert.equal(h.render().pending(h.r), true);
    const writes = h.calls.filter((c) => c.options?.method === "POST").length;
    assert.equal(await h.render().discard(h.r), true);
    assert.equal(h.render().pending(h.r), false);
    assert.equal(h.render().name(h.r), "LATEST");
    assert.equal(h.calls.filter((c) => c.discarded).length, 1);
    assert.equal(h.calls.filter((c) => c.options?.method === "POST").length, writes);
  } finally {
    h.close();
  }
});

test("display read-context changes leave rename and unknown-ACK journal recovery on their original operation lane", async () => {
  const ack = deferred(),
    lookup = deferred();
  const h = harness((call) =>
    call.path.endsWith("commands")
      ? ack.promise
      : call.path.includes("/operations/")
        ? lookup.promise
        : undefined,
  );
  try {
    h.workspace({ resourceDisplay: { readKey: "context_A", prepare: () => null } });
    await h.ready();
    const scope = h.render().scope;
    const write = h.render().rename(h.r, "NEW");
    await settle();
    const command = h.calls.find((c) => c.path?.endsWith("commands"));
    assert.ok(command);
    const packet = h.packets.get("A"),
      before = h.calls.length;
    h.workspace({ resourceDisplay: { readKey: "context_B", prepare: () => null } });
    h.render();
    await settle();
    assert.equal(h.render().scope, scope);
    assert.equal(h.render().busy, true);
    assert.equal(h.render().pending(h.r), true);
    assert.equal(h.packets.get("A"), packet);
    assert.equal(command.options.signal.aborted, false);
    assert.equal(h.calls.length, before);
    ack.resolve(response({}, 503));
    assert.equal(await write, false);
    const recovering = h.render().recover(h.r);
    await settle();
    const original = h.calls.find((c) => c.path?.includes("/operations/"));
    assert.ok(original);
    h.workspace({ resourceDisplay: { readKey: "context_C", prepare: () => null } });
    h.render();
    await settle();
    assert.equal(original.options.signal.aborted, false);
    assert.equal(h.packets.get("A"), packet);
    lookup.resolve(response({}, 404));
    assert.equal(await recovering, false);
    assert.equal(h.render().error, "operation_pending");
    assert.equal(h.render().pending(h.r), true);
    assert.equal(h.calls.filter((c) => c.options?.method === "POST").length, 1);
  } finally {
    ack.resolve(response({}, 503));
    lookup.resolve(response({}, 404));
    h.close();
  }
});
