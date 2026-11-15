const test = require("node:test"),
  assert = require("node:assert/strict");
const { hooks, jsx, all } = require("./resource-ui-harness.cjs");
const {
  compile,
  catalogue,
  channels,
  stocks,
  response,
  settle,
  deferred,
  contracts,
  ref,
} = require("./resource-library-helpers.cjs");
function harness({ legacy = false, externalWatchlist = true } = {}) {
  const ui = hooks(),
    calls = [],
    pending = [],
    events = new Map(),
    writeGate = deferred(),
    watchGate = deferred(),
    namesGate = deferred();
  let owner = "owner_A:1",
    active = true,
    visible = true,
    clock = 100000,
    hold = false,
    holdNames = false,
    demand,
    current,
    tree;
  let workspace = {
    owner: null,
    authenticated: true,
    configured: true,
    phase: "checking",
    vault: null,
    vaultGeneration: 0,
    sources: [],
    selectedSourceId: null,
    sourceMetadata: null,
    content: null,
    canWriteState: false,
    needsDeviceApproval: false,
    newSource: false,
    busy: "loading",
    error: "",
    openDisplayNames: async () => [],
    loadDisplayNamePending: async () => null,
    readStored: async () => {
      throw Error("Read-only synthetic workspace must not start Portfolio reads");
    },
  };
  const requestPrivate = async (service, path, key, options) => {
    const call = { service, path, key, options };
    calls.push(call);
    if (path.endsWith("/resources/catalogue")) {
      if (hold) {
        const gate = deferred();
        pending.push(gate);
        return gate.promise;
      }
      return response(catalogue());
    }
    if (path.endsWith("/private-display-names/capabilities"))
      return holdNames ? namesGate.promise : response({}, 404);
    if (path.endsWith("/watchlist")) return watchGate.promise;
    if (path.endsWith("/channel-follows"))
      return options.method === "PUT" ? writeGate.promise : response(channels());
    throw Error("Unexpected synthetic request");
  };
  const auth = {
    useAuth: () => ({
      status: "authenticated",
      profile: {},
      sessionKey: owner,
      agentHubConfigured: true,
      requestPrivate,
    }),
  };
  const globals = {
    document: {
      get visibilityState() {
        return visible ? "visible" : "hidden";
      },
      addEventListener(k, f) {
        if (!events.has(k)) events.set(k, new Set());
        events.get(k).add(f);
      },
      removeEventListener: (k, f) => events.get(k)?.delete(f),
    },
    window: { setTimeout, clearTimeout },
    setTimeout,
    clearTimeout,
    Date: class extends Date {
      static now() {
        return clock;
      }
    },
  };
  const names = compile(
    "../components/useDisplayNames.ts",
    { react: ui.react, "./AuthProvider": auth },
    globals,
  );
  const hook = compile(
    "../components/useResourceLibrary.ts",
    { react: ui.react, "@/components/AuthProvider": auth, "@/lib/resource-library": contracts },
    globals,
  );
  const lib = compile(
    "../components/ResourceLibrary.tsx",
    {
      react: ui.react,
      "react/jsx-runtime": { jsx, jsxs: jsx },
      "next-intl": { useTranslations: () => (k) => k },
      "./useResourceLibrary": hook,
      "./AuthProvider": auth,
      "@/lib/resource-library": contracts,
      "./ResourceLibrary.module.css": { __esModule: true, default: {} },
    },
    globals,
  );
  const resources = compile(
    "../components/ResourcesPanel.tsx",
    {
      react: ui.react,
      "react/jsx-runtime": { jsx, jsxs: jsx },
      "next-intl": { useTranslations: () => (k) => k },
      "next/dynamic": { __esModule: true, default: () => () => null },
      "@/components/useHoldingsWorkspace": {},
      "@/lib/holdings-facts": compile("../lib/holdings-facts.ts"),
      "./HoldingsEditor": { __esModule: true, default: () => null },
      "./ResourceLibrary": lib,
      "./PasskeyHelp": {},
      "./HoldingsSourceBar": {},
      "./useDisplayNames": names,
      "./ResourcesPanel.module.css": { __esModule: true, default: {} },
    },
    globals,
  );
  const shared = () => ({
    sessionKey: owner,
    items: stocks().items,
    limit: 50,
    loading: false,
    busy: false,
  });
  const render = () =>
    ui.render(() => {
      let node;
      if (legacy)
        node = lib.default({
          active,
          watchlist: externalWatchlist ? shared() : undefined,
          holdingsCatalogueNeeded: demand,
          children: "LEGACY",
        });
      else {
        const panel = resources.default({ workspace, active, watchlist: shared() });
        const view = panel.type(panel.props);
        const child = all(view, (n) => n.type === lib.default)[0];
        node = child.type(child.props);
      }
      current = node.props.model;
      return (tree = node.type(node.props));
    });
  return {
    calls,
    pending,
    writeGate,
    watchGate,
    namesGate,
    render,
    get tree() {
      return tree;
    },
    get model() {
      return current;
    },
    cats: () => calls.filter((c) => c.path.endsWith("/resources/catalogue")),
    async settle() {
      await settle();
      render();
      await settle();
      return render();
    },
    modelPatch(v) {
      workspace = { ...workspace, ...v };
      return render();
    },
    unlock() {
      workspace = {
        ...workspace,
        owner,
        phase: "unlocked",
        vault: { vaultId: "vault_A", rootKeyId: "root_A", version: 1 },
        vaultGeneration: 1,
        busy: null,
      };
      return render();
    },
    filter(kind) {
      const b = all(tree, (n) => n.type === "button" && n.props.children === "kinds." + kind)[0];
      assert.ok(b);
      b.props.onClick();
      return render();
    },
    active(v) {
      active = v;
      return render();
    },
    visibility(v) {
      visible = v;
      for (const f of events.get("visibilitychange") ?? []) f();
      return render();
    },
    owner(v) {
      owner = v;
      return render();
    },
    hold(v) {
      hold = v;
    },
    holdNames(v) {
      holdNames = v;
    },
    demand(v) {
      demand = v;
      return render();
    },
    publish(snapshotId = "snapshot_A") {
      const source = workspace.sources[0];
      assert.ok(source);
      workspace = {
        ...workspace,
        selectedSourceId: source.resourceRef.resourceId,
        sourceMetadata: { state: "active", source, snapshotId },
        content: { data: { snapshotId } },
      };
      return render();
    },
    advance(ms) {
      clock += ms;
    },
    async reply(index, data = catalogue(), status = 200) {
      pending[index].resolve(response(data, status));
      return this.settle();
    },
    close: ui.close,
  };
}
test("actual ResourcesView names scope holds catalogue through unknown current and archive stages and starts once when unlocked even with aliases disabled", async () => {
  const h = harness();
  try {
    h.render();
    await h.settle();
    assert.equal(h.cats().length, 0);
    assert.equal(h.model.catalogue.data, null);
    assert.equal(h.model.catalogue.loading, false);
    h.modelPatch({ owner: "owner_A:1" });
    await h.settle();
    assert.equal(h.cats().length, 0);
    h.modelPatch({
      vault: { vaultId: "vault_A", rootKeyId: "root_A", version: 1 },
      vaultGeneration: 1,
    });
    await h.settle();
    assert.equal(h.cats().length, 0);
    h.unlock();
    await h.settle();
    assert.equal(h.cats().length, 1);
    assert.ok(h.model.catalogue.data);
    assert.equal(h.calls.filter((c) => c.path.endsWith("/capabilities")).length, 1);
    assert.equal(h.model.catalogue.error, "");
  } finally {
    h.close();
  }
});
test("locked and approval-needed holdings remain unknown, while explicit other filters retain Google-only lists and original catalogue demand", async () => {
  const h = harness();
  try {
    h.render();
    await h.settle();
    assert.equal(h.cats().length, 0);
    h.filter("channel_follows");
    await h.settle();
    assert.equal(h.cats().length, 1);
    assert.equal(h.model.follows.data.items[0].name, "Synthetic Creator");
    h.filter("holdings");
    await h.settle();
    assert.equal(h.model.catalogue.data, null);
    assert.equal(h.model.catalogue.loading, false);
    h.unlock();
    h.modelPatch({ needsDeviceApproval: true });
    await h.settle();
    assert.equal(h.model.catalogue.data, null);
    h.modelPatch({ phase: "locked", needsDeviceApproval: false });
    h.filter("watchlist");
    await h.settle();
    assert.ok(h.model.catalogue.data);
    assert.equal(
      h.calls.filter((c) => c.path.endsWith("/channel-follows") && c.options.method === "GET")
        .length,
      1,
    );
  } finally {
    h.close();
  }
});
test("catalogue demand cancellation does not abort a User write, and the acknowledgement cannot force an unneeded catalogue request", async () => {
  const h = harness();
  try {
    h.render();
    h.filter("channel_follows");
    await h.settle();
    const write = h.model.saveFollows(
      channels().items.map(({ name, handleOrUrl, note }) => ({ name, handleOrUrl, note })),
    );
    await settle();
    const put = h.calls.find((c) => c.options.method === "PUT");
    assert.ok(put);
    h.filter("holdings");
    await h.settle();
    assert.equal(put.options.signal.aborted, false);
    const before = h.cats().length;
    h.writeGate.resolve(response(channels("Synthetic Creator", 2)));
    assert.equal(await write, true);
    await h.settle();
    assert.equal(h.cats().length, before);
    assert.equal(h.calls.filter((c) => c.options.method === "PUT").length, 1);
    h.filter("channel_follows");
    await h.settle();
    assert.equal(h.cats().length, before + 1);
  } finally {
    h.close();
  }
});
test("a locked late catalogue cannot publish and returning to the same stable scope reuses only a completed receipt within its original30s TTL", async () => {
  const h = harness();
  try {
    h.hold(true);
    h.render();
    h.unlock();
    await h.settle();
    assert.equal(h.cats().length, 1);
    h.modelPatch({ phase: "locked" });
    assert.equal(h.cats()[0].options.signal.aborted, true);
    assert.equal(h.model.catalogue.data, null);
    await h.reply(0);
    assert.equal(h.model.catalogue.data, null);
    h.unlock();
    await h.settle();
    assert.equal(h.cats().length, 2);
    await h.reply(1);
    h.modelPatch({ phase: "locked" });
    h.advance(10000);
    h.unlock();
    await h.settle();
    assert.equal(h.cats().length, 2);
    h.modelPatch({ phase: "locked" });
    h.advance(20001);
    h.unlock();
    await h.settle();
    assert.equal(h.cats().length, 3);
    await h.reply(2);
  } finally {
    h.close();
  }
});
test("Owner, vault, generation, full source and visibility changes preserve strongest masking and fence cancelled outcomes", async () => {
  for (const change of ["owner", "vault", "generation", "source", "epoch", "hidden", "inactive"]) {
    const h = harness();
    try {
      h.hold(true);
      h.render();
      h.modelPatch({ sources: [{ resourceRef: ref("holdings"), sourceEpoch: 1 }] });
      h.unlock();
      await h.settle();
      if (change === "owner") {
        h.owner("owner_B:2");
        assert.equal(h.model.catalogue.data, null);
        await h.reply(0);
        assert.equal(h.cats().length, 1);
        h.modelPatch({ owner: "owner_B:2", phase: "unlocked" });
      } else if (change === "vault") {
        h.modelPatch({ vault: { vaultId: "vault_B", rootKeyId: "root_B", version: 1 } });
        assert.equal(h.model.catalogue.data, null);
      } else if (change === "generation") {
        h.modelPatch({ vaultGeneration: 2 });
        assert.equal(h.model.catalogue.data, null);
      } else if (change === "source") {
        h.modelPatch({
          sources: [{ resourceRef: ref("holdings", "other_source"), sourceEpoch: 1 }],
        });
        assert.equal(h.model.catalogue.data, null);
      } else if (change === "epoch") {
        h.modelPatch({ sources: [{ resourceRef: ref("holdings"), sourceEpoch: 2 }] });
        assert.equal(h.model.catalogue.data, null);
      } else if (change === "hidden") {
        h.visibility(false);
        assert.equal(h.model.catalogue.data, null);
        await h.reply(0);
        h.visibility(true);
      } else {
        h.active(false);
        assert.equal(h.cats()[0].options.signal.aborted, true);
        await h.reply(0);
        assert.equal(h.model.catalogue.data, null);
        h.active(true);
      }
      await h.settle();
      assert.equal(h.cats().length, 2);
      await h.reply(1);
      assert.equal(h.model.catalogue.stale, false);
    } finally {
      h.close();
    }
  }
});
test("a needed read failure keeps explicit retry, whereas retry and publication during private initialization do not start catalogue work", async () => {
  const h = harness();
  try {
    h.hold(true);
    h.render();
    const premature = h.model.reload("catalogue");
    await h.settle();
    assert.equal(h.cats().length, 0);
    await premature;
    h.unlock();
    await h.settle();
    await h.reply(0, {}, 503);
    assert.ok(h.model.catalogue.error);
    await h.settle();
    assert.equal(h.cats().length, 1);
    const retry = h.model.reload("catalogue");
    await h.settle();
    assert.equal(h.cats().length, 2);
    await h.reply(1);
    await retry;
    h.modelPatch({ phase: "checking" });
    assert.equal(h.model.catalogue.data, null);
    await h.model.reload("catalogue");
    assert.equal(h.cats().length, 2);
  } finally {
    h.close();
  }
});
test("external legacy callers without the new prerequisite keep their catalogue demand", async () => {
  const h = harness({ legacy: true });
  try {
    h.render();
    await h.settle();
    assert.equal(h.cats().length, 1);
    assert.ok(h.model.catalogue.data);
  } finally {
    h.close();
  }
});

test("pending name capability and Portfolio work never postpone the verified-scope catalogue demand", async () => {
  const h = harness();
  try {
    h.holdNames(true);
    h.render();
    h.unlock();
    h.modelPatch({ busy: "loading" });
    await h.settle();
    assert.equal(h.cats().length, 1);
    assert.ok(h.model.catalogue.data);
    assert.equal(h.calls.filter((c) => c.path.endsWith("/capabilities")).length, 1);
    h.namesGate.resolve(response({}, 404));
    await h.settle();
    assert.equal(h.cats().length, 1);
  } finally {
    h.close();
  }
});
test("first same-scope publication still matches the in-flight DTO and a genuinely new head invalidates immediately", async () => {
  const h = harness();
  try {
    h.hold(true);
    h.render();
    h.modelPatch({ sources: [{ resourceRef: ref("holdings"), sourceEpoch: 1 }] });
    h.unlock();
    await h.settle();
    h.publish();
    await h.settle();
    assert.equal(h.cats().length, 1);
    await h.reply(0);
    assert.equal(h.cats().length, 1);
    assert.equal(h.model.catalogue.stale, false);
    const selected = [];
    h.model.useForTask(h.model.catalogue.data.groups[0].items[0], (v) => selected.push(v));
    assert.equal(selected.length, 1);
    h.publish("snapshot_B");
    await h.settle();
    assert.equal(h.cats().length, 2);
    assert.equal(h.model.catalogue.stale, true);
    const next = catalogue();
    next.groups[0].items[0].snapshotId = "snapshot_B";
    await h.reply(1, next);
    assert.equal(h.model.catalogue.stale, false);
    h.modelPatch({ phase: "checking" });
    assert.equal(h.model.catalogue.data, null);
    h.model.useForTask(next.groups[0].items[0], (v) => selected.push(v));
    assert.equal(selected.length, 1);
    await h.model.reload("catalogue");
    assert.equal(h.cats().length, 2);
  } finally {
    h.close();
  }
});
test("an actual first import after an empty initialized catalogue still reads its new head", async () => {
  const h = harness();
  try {
    h.hold(true);
    h.render();
    h.modelPatch({ sources: [{ resourceRef: ref("holdings"), sourceEpoch: 1 }] });
    h.unlock();
    await h.settle();
    const empty = catalogue();
    empty.groups[0].items = [];
    empty.groups[0].status = "uninitialized";
    await h.reply(0, empty);
    h.publish();
    await h.settle();
    assert.equal(h.cats().length, 2);
    await h.reply(1);
    assert.equal(h.model.catalogue.stale, false);
  } finally {
    h.close();
  }
});
test("catalogue-only prerequisite changes preserve an in-flight User watchlist and stable operation callbacks", async () => {
  const h = harness({ legacy: true, externalWatchlist: false });
  try {
    h.hold(true);
    h.render();
    await h.settle();
    const watch = h.calls.find((c) => c.path.endsWith("/watchlist"));
    assert.ok(watch);
    const reload = h.model.reload,
      save = h.model.saveFollows;
    assert.equal(h.cats().length, 1);
    h.demand(false);
    assert.equal(h.cats()[0].options.signal.aborted, true);
    assert.equal(watch.options.signal.aborted, false);
    assert.equal(h.model.reload, reload);
    assert.equal(h.model.saveFollows, save);
    h.watchGate.resolve(response(stocks()));
    await h.reply(0);
    assert.equal(h.model.catalogue.data, null);
    assert.equal(h.model.watchlist.data.items[0].symbol, "SYNTH");
    h.demand(true);
    await h.settle();
    assert.equal(h.cats().length, 2);
    await h.reply(1);
    assert.equal(h.calls.filter((c) => c.path.endsWith("/watchlist")).length, 1);
  } finally {
    h.close();
  }
});
test("a rapid leave and return does not let the old cancelled outcome clear the replacement catalogue loading state", async () => {
  const h = harness();
  try {
    h.hold(true);
    h.render();
    h.unlock();
    await h.settle();
    h.active(false);
    assert.equal(h.cats()[0].options.signal.aborted, true);
    h.active(true);
    await h.settle();
    assert.equal(h.cats().length, 2);
    assert.equal(h.model.catalogue.loading, true);
    await h.reply(0);
    assert.equal(h.model.catalogue.loading, true);
    assert.equal(h.model.catalogue.data, null);
    await h.reply(1);
    assert.equal(h.model.catalogue.loading, false);
    assert.ok(h.model.catalogue.data);
  } finally {
    h.close();
  }
});
test("a completed matching publication survives a same-scope initialization gap without extending its original receipt", async () => {
  const h = harness();
  try {
    h.hold(true);
    h.render();
    h.modelPatch({ sources: [{ resourceRef: ref("holdings"), sourceEpoch: 1 }] });
    h.unlock();
    h.publish();
    await h.reply(0);
    h.advance(10000);
    h.modelPatch({ phase: "checking" });
    assert.equal(h.model.catalogue.data, null);
    h.unlock();
    await h.settle();
    assert.equal(h.cats().length, 1);
    assert.equal(h.model.catalogue.stale, false);
    h.modelPatch({ phase: "checking" });
    h.advance(20001);
    h.unlock();
    await h.settle();
    assert.equal(h.cats().length, 2);
    await h.reply(1);
  } finally {
    h.close();
  }
});
