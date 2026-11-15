const test = require("node:test"),
  assert = require("node:assert/strict");
const { hooks, jsx } = require("./resource-ui-harness.cjs");
const {
  compile,
  catalogue,
  stocks,
  channels,
  response,
  settle,
  deferred,
  contracts,
  ref,
} = require("./resource-library-helpers.cjs");
function harness({ initialVersion, legacy = false } = {}) {
  const ui = hooks(),
    calls = [],
    gates = [],
    writeGate = deferred(),
    events = new Map();
  let owner = "owner_A:1",
    scope = "vault_A:1:version1:epoch1",
    active = true,
    visible = true,
    now = 100000,
    model;
  const requestPrivate = async (service, path, key, options) => {
    calls.push({ service, path, key, options });
    if (path === "/api/v1/channel-follows")
      return options.method === "PUT" ? writeGate.promise : response(channels());
    assert.equal(path, "/api/v2/resources/catalogue");
    const gate = deferred();
    gates.push(gate);
    return gate.promise;
  };
  const auth = {
    useAuth: () => ({
      status: "authenticated",
      sessionKey: owner,
      profile: {},
      agentHubConfigured: true,
      requestPrivate,
    }),
  };
  const globals = {
    document: {
      get visibilityState() {
        return visible ? "visible" : "hidden";
      },
      addEventListener: (k, f) => events.set(k, f),
      removeEventListener: (k) => events.delete(k),
    },
    window: { setTimeout, clearTimeout },
    Date: class extends Date {
      static now() {
        return now;
      }
    },
  };
  const hook = compile(
    "../components/useResourceLibrary.ts",
    { react: ui.react, "@/components/AuthProvider": auth, "@/lib/resource-library": contracts },
    globals,
  );
  const library = compile(
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
  const props = {
    holdingsVersion: initialVersion,
    holdingsPublication: null,
    watchlist: { sessionKey: owner, items: stocks().items, loading: false, limit: 50 },
    children: "SYNTHETIC_HOLDINGS",
  };
  const render = () =>
    ui.render(() => {
      const tree = library.default({ ...props, active, workspaceScope: scope });
      model = tree.props.model;
      return library.ResourceLibraryView(tree.props);
    });
  return {
    writeGate,
    calls,
    gates,
    render,
    get model() {
      return model;
    },
    publish(snapshotId = "snapshot_A", patch = {}) {
      props.holdingsVersion = snapshotId;
      props.holdingsPublication = legacy
        ? null
        : {
            owner,
            workspaceScope: scope,
            ref: ref("holdings"),
            sourceEpoch: 1,
            snapshotId,
            ...patch,
          };
      return render();
    },
    async reply(index, value = catalogue(), status = 200) {
      gates[index].resolve(response(value, status));
      await settle();
      render();
      await settle();
      return render();
    },
    advance(ms) {
      now += ms;
    },
    active(v) {
      active = v;
      return render();
    },
    owner(v) {
      owner = v;
      props.watchlist = { ...props.watchlist, sessionKey: v };
      props.holdingsPublication = null;
      props.holdingsVersion = undefined;
      scope = "vault_B:1";
      return render();
    },
    visibility(v) {
      visible = v;
      events.get("visibilitychange")?.();
      return render();
    },
    watchlist(symbol) {
      props.watchlist = { ...props.watchlist, items: stocks(symbol).items };
      return render();
    },
    scope(v) {
      scope = v;
      props.holdingsPublication = null;
      props.holdingsVersion = undefined;
      return render();
    },
    close: ui.close,
  };
}
const snapshot = (id, patch = {}) => {
  const data = catalogue();
  Object.assign(data.groups[0].items[0], { snapshotId: id, ...patch });
  return data;
};
test("first bound snapshot waits for the current same-scope catalogue and reuses only its exact matching head", async () => {
  const h = harness();
  try {
    h.render();
    await settle();
    h.publish();
    await settle();
    assert.equal(h.calls.length, 1);
    assert.equal(h.calls[0].options.signal.aborted, false);
    await h.reply(0);
    assert.equal(h.calls.length, 1);
    assert.equal(h.model.catalogue.stale, false);
    assert.equal(h.model.catalogue.error, "");
    assert.ok(h.model.catalogue.data);
  } finally {
    h.close();
  }
});
test("a successful mismatching first catalogue requires one fresh read before the published head is usable", async () => {
  const h = harness();
  try {
    h.render();
    await settle();
    h.publish();
    assert.equal(h.calls.length, 1);
    await h.reply(0, snapshot("snapshot_OLD"));
    assert.equal(h.calls.length, 2);
    assert.equal(h.model.catalogue.stale, true);
    await h.reply(1);
    assert.equal(h.model.catalogue.stale, false);
    assert.equal(h.model.catalogue.error, "");
  } finally {
    h.close();
  }
});
for (const [label, patch] of [
  ["foreign resource", { ref: ref("holdings", "other_source") }],
  ["different incarnation", { ref: { ...ref("holdings"), incarnation: "other_incarnation" } }],
  ["different epoch", { sourceEpoch: 2 }],
])
  test(`snapshotId alone cannot reuse a ${label} catalogue row`, async () => {
    const h = harness();
    try {
      h.render();
      await settle();
      h.publish();
      assert.equal(h.calls.length, 1);
      await h.reply(0, snapshot("snapshot_A", patch));
      assert.equal(h.calls.length, 2);
      assert.equal(h.model.catalogue.stale, true);
      await h.reply(1);
      assert.equal(h.model.catalogue.stale, false);
    } finally {
      h.close();
    }
  });
test("first actual import from an empty source still requests discovery, while a completed exact head is reused without extending its receipt", async () => {
  for (const empty of [true, false]) {
    const h = harness();
    try {
      h.render();
      await settle();
      const data = catalogue();
      if (empty) {
        data.groups[0].items = [];
        data.groups[0].status = "uninitialized";
      }
      await h.reply(0, data);
      h.advance(10000);
      h.publish();
      await settle();
      assert.equal(h.calls.length, empty ? 2 : 1);
      if (empty) await h.reply(1);
      else {
        h.active(false);
        h.advance(20001);
        h.active(true);
        await settle();
        assert.equal(
          h.calls.length,
          2,
          "Original catalogue timestamp expires at30s, not publication+30s",
        );
        await h.reply(1);
      }
    } finally {
      h.close();
    }
  }
});
test("legacy callers and genuine A-to-B publication retain immediate invalidation", async () => {
  for (const legacy of [true, false]) {
    const h = harness({ legacy });
    try {
      h.render();
      await settle();
      h.publish();
      await settle();
      if (legacy) {
        assert.equal(h.calls.length, 2);
        await h.reply(1);
      } else {
        assert.equal(h.calls.length, 1);
        await h.reply(0);
      }
      h.publish("snapshot_B");
      await settle();
      assert.equal(h.calls.length, legacy ? 3 : 2);
      assert.equal(h.model.catalogue.loading, true);
      await h.reply(legacy ? 2 : 1, snapshot("snapshot_B"));
      assert.equal(h.model.catalogue.stale, false);
    } finally {
      h.close();
    }
  }
});
test("an explicit retry supersedes the old observer and a new mismatching read remains stale instead of claiming freshness", async () => {
  const h = harness();
  try {
    h.render();
    await settle();
    h.publish();
    assert.equal(h.calls.length, 1);
    const retry = h.model.reload("catalogue");
    await settle();
    assert.equal(h.calls.length, 2);
    assert.equal(h.calls[0].options.signal.aborted, true);
    await h.reply(0);
    assert.equal(h.calls.length, 2);
    await h.reply(1, snapshot("snapshot_OLD"));
    await retry;
    h.render();
    assert.equal(h.calls.length, 2, "Superseded observer must not schedule another GET");
    assert.equal(h.model.catalogue.stale, true);
    assert.ok(h.model.catalogue.error);
    let selected = 0;
    h.model.useForTask(h.model.catalogue.data.groups[0].items[0], () => selected++);
    assert.equal(selected, 0);
  } finally {
    h.close();
  }
});
test("a matching explicit retry can complete after an old read cancellation without a duplicate or late overwrite", async () => {
  const h = harness();
  try {
    h.render();
    await settle();
    h.publish();
    assert.equal(h.calls.length, 1);
    const retry = h.model.reload("catalogue");
    await settle();
    await h.reply(1);
    await retry;
    await h.reply(0, snapshot("snapshot_OLD"));
    assert.equal(h.calls.length, 2);
    assert.equal(h.model.catalogue.stale, false);
    assert.equal(h.model.catalogue.data.groups[0].items[0].snapshotId, "snapshot_A");
  } finally {
    h.close();
  }
});
test("leaving cancels observers; return and Owner or epoch changes cannot publish or supplement the old scope", async () => {
  for (const change of ["navigation", "owner", "epoch"]) {
    const h = harness();
    try {
      h.render();
      await settle();
      h.publish();
      assert.equal(h.calls.length, 1);
      if (change === "navigation") {
        h.active(false);
        h.active(true);
      } else if (change === "owner") h.owner("owner_B:2");
      else h.scope("vault_A:1:version1:epoch2");
      await settle();
      assert.equal(h.calls.length, 2);
      await h.reply(0, snapshot("snapshot_OLD"));
      assert.equal(h.calls.length, 2);
      assert.equal(h.model.catalogue.data, null);
      await h.reply(1);
      assert.equal(h.calls.length, 2);
      assert.equal(h.model.catalogue.stale, false);
    } finally {
      h.close();
    }
  }
});
test("failed or malformed pending discovery keeps its explicit retry and is not an automatic supplement hint", async () => {
  for (const malformed of [true, false]) {
    const h = harness();
    try {
      h.render();
      await settle();
      h.publish();
      assert.equal(h.calls.length, 1);
      const data = catalogue();
      if (malformed) data.groups[0].items[0].extra = "bad";
      await h.reply(0, data, malformed ? 200 : 503);
      assert.equal(h.calls.length, 1);
      assert.ok(h.model.catalogue.error);
      assert.equal(h.model.catalogue.data, null);
    } finally {
      h.close();
    }
  }
});
for (const patch of [
  { owner: "other_owner" },
  { workspaceScope: "other_scope" },
  { ref: { ...ref("holdings"), incarnation: "other" }, sourceEpoch: 0 },
])
  test(`unbound publication metadata retains conservative legacy invalidation: ${JSON.stringify(patch)}`, async () => {
    const h = harness();
    try {
      h.render();
      await settle();
      h.publish("snapshot_A", patch);
      await settle();
      assert.equal(h.model.publicationBound, false);
      assert.equal(h.calls.length, 2);
      assert.equal(h.calls[0].options.signal.aborted, true);
      await h.reply(1);
      assert.equal(h.model.catalogue.stale, false);
    } finally {
      h.close();
    }
  });
test("a source switch cancels the first observer even when both sources use the same snapshot identifier", async () => {
  const h = harness();
  try {
    h.render();
    await settle();
    h.publish();
    assert.equal(h.calls.length, 1);
    const other = ref("holdings", "other_source");
    h.publish("snapshot_A", { ref: other });
    await settle();
    assert.equal(h.calls.length, 2);
    assert.equal(h.calls[0].options.signal.aborted, true);
    await h.reply(0);
    assert.equal(h.calls.length, 2);
    await h.reply(1, snapshot("snapshot_A", { ref: other }));
    assert.equal(h.model.catalogue.stale, false);
    assert.equal(h.model.catalogue.data.groups[0].items[0].ref.resourceId, "other_source");
  } finally {
    h.close();
  }
});
test("the actual ResourcesPanel binds only the selected current source metadata and verified content pair", () => {
  const ui = hooks(),
    Library = () => null;
  const r = ref("holdings", "source_A"),
    source = { resourceRef: r, sourceEpoch: 2 };
  const base = {
    owner: "owner_A",
    authenticated: true,
    configured: true,
    phase: "unlocked",
    vault: { vaultId: "vault_A", version: 3 },
    vaultGeneration: 1,
    needsDeviceApproval: false,
    sources: [source],
    selectedSourceId: "source_A",
    sourceMetadata: { source, revision: 1, snapshotId: "snapshot_A", state: "active" },
    content: { data: { snapshotId: "snapshot_A" } },
    newSource: false,
  };
  let model = base;
  const panel = compile("../components/ResourcesPanel.tsx", {
    react: ui.react,
    "react/jsx-runtime": { jsx, jsxs: jsx },
    "next-intl": { useTranslations: () => (k) => k },
    "next/dynamic": { __esModule: true, default: () => () => null },
    "@/components/useHoldingsWorkspace": {},
    "@/lib/holdings-facts": compile("../lib/holdings-facts.ts"),
    "./HoldingsEditor": { __esModule: true, default: () => null },
    "./ResourceLibrary": { __esModule: true, default: Library },
    "./PasskeyHelp": {},
    "./HoldingsSourceBar": {},
    "./useDisplayNames": { useDisplayNames: () => ({ scope: "names" }) },
    "./ResourcesPanel.module.css": { __esModule: true, default: {} },
  });
  const all = require("./resource-ui-harness.cjs").all;
  const draw = () =>
    ui.render(() => {
      const p = panel.default({ workspace: model, active: false });
      return p.type(p.props);
    });
  const publication = () => all(draw(), (n) => n.type === Library)[0].props;
  try {
    let p = publication();
    assert.deepEqual(JSON.parse(JSON.stringify(p.holdingsPublication)), {
      owner: "owner_A",
      workspaceScope: p.workspaceScope,
      ref: r,
      sourceEpoch: 2,
      snapshotId: "snapshot_A",
    });
    for (const patch of [
      { phase: "locked" },
      { needsDeviceApproval: true },
      { newSource: true },
      { selectedSourceId: "missing_source" },
      { sourceMetadata: null },
      { content: null },
      { sourceMetadata: { ...base.sourceMetadata, state: "revoking" } },
      { sourceMetadata: { ...base.sourceMetadata, snapshotId: "other_snapshot" } },
      {
        sourceMetadata: {
          ...base.sourceMetadata,
          source: { resourceRef: { ...r, incarnation: "old_incarnation" }, sourceEpoch: 2 },
        },
      },
      { sourceMetadata: { ...base.sourceMetadata, source: { resourceRef: r, sourceEpoch: 1 } } },
    ]) {
      model = { ...base, ...patch };
      assert.equal(publication().holdingsPublication, null, JSON.stringify(patch));
    }
    model = { ...base, vaultGeneration: 2 };
    p = publication();
    assert.equal(p.holdingsPublication.workspaceScope, p.workspaceScope);
    assert.notEqual(p.workspaceScope, JSON.stringify(["owner_A", "vault_A", 1, 3, [[r, 2]]]));
  } finally {
    ui.close();
  }
});
test("a legitimate shared-watchlist refresh changes the read serial without allowing an old publication observer to supplement", async () => {
  const h = harness();
  try {
    h.render();
    await settle();
    h.publish();
    assert.equal(h.calls.length, 1);
    h.watchlist("NEXT");
    await settle();
    assert.equal(h.calls.length, 2);
    await h.reply(0);
    await h.reply(1, snapshot("snapshot_OLD"));
    assert.equal(h.calls.length, 2);
    assert.equal(h.model.catalogue.stale, true);
    assert.equal(h.model.catalogue.error, "reload_required");
  } finally {
    h.close();
  }
});
test("a private validated receipt cannot be rewritten through the public catalogue view", async () => {
  const h = harness();
  try {
    h.render();
    await settle();
    await h.reply(0);
    h.model.catalogue.data.groups[0].items[0].snapshotId = "snapshot_B";
    h.publish("snapshot_B");
    await settle();
    assert.equal(h.calls.length, 2);
    await h.reply(1, snapshot("snapshot_B"));
    assert.equal(h.model.catalogue.stale, false);
  } finally {
    h.close();
  }
});
test("a second mismatch or hidden document requires explicit recovery and never loops or extends freshness", async () => {
  for (const hide of [true, false]) {
    const h = harness();
    try {
      h.render();
      await settle();
      h.publish();
      if (hide) {
        h.visibility(false);
        await h.reply(0);
        assert.equal(h.calls.length, 1);
        h.visibility(true);
        await settle();
        assert.equal(h.calls.length, 2);
        await h.reply(1);
      } else {
        await h.reply(0, snapshot("snapshot_OLD"));
        await h.reply(1, snapshot("snapshot_OLD"));
        h.render();
        await settle();
        assert.equal(h.calls.length, 2);
        assert.equal(h.model.catalogue.stale, true);
        assert.equal(h.model.catalogue.error, "reload_required");
        const retry = h.model.reload("catalogue");
        await settle();
        await h.reply(2);
        await retry;
        h.render();
      }
      assert.equal(h.model.catalogue.stale, false);
    } finally {
      h.close();
    }
  }
});
test("a discovery failure that completed before first materialization retains explicit retry rather than becoming a transport hint", async () => {
  for (const malformed of [true, false]) {
    const h = harness();
    try {
      h.render();
      await settle();
      const data = catalogue();
      if (malformed) data.groups[0].items[0].extra = "bad";
      await h.reply(0, data, malformed ? 200 : 503);
      assert.ok(h.model.catalogue.error);
      h.publish();
      await settle();
      assert.equal(h.calls.length, 1);
      assert.ok(h.model.catalogue.error);
      const retry = h.model.reload("catalogue");
      await settle();
      await h.reply(1);
      await retry;
      h.render();
      assert.equal(h.model.catalogue.stale, false);
    } finally {
      h.close();
    }
  }
});
test("publication during a follow edit preserves its pending write and uses only the original acknowledgement refresh", async () => {
  const h = harness(),
    catalogueCalls = () => h.calls.filter((c) => c.path.endsWith("/catalogue"));
  try {
    h.render();
    await settle();
    await h.model.reload("follows");
    h.render();
    const write = h.model.saveFollows(
      channels().items.map(({ name, handleOrUrl, note }) => ({ name, handleOrUrl, note })),
    );
    await settle();
    const put = h.calls.find((c) => c.options.method === "PUT");
    assert.equal(put.options.json.expectedRevision, 1);
    assert.equal(catalogueCalls().length, 1);
    h.publish();
    await settle();
    assert.equal(
      catalogueCalls().length,
      1,
      "Publication does not read or confirm discovery before write ACK",
    );
    assert.equal(put.options.signal.aborted, false);
    h.writeGate.resolve(response(channels("Synthetic Creator", 2)));
    assert.equal(await write, true);
    await settle();
    h.render();
    assert.equal(catalogueCalls().length, 2);
    await h.reply(1);
    await h.reply(0, snapshot("snapshot_OLD"));
    assert.equal(catalogueCalls().length, 2);
    assert.equal(h.model.catalogue.stale, false);
    assert.equal(h.calls.filter((c) => c.options.method === "PUT").length, 1);
  } finally {
    h.close();
  }
});
