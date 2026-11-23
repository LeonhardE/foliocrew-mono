const assert = require("node:assert/strict"),
  test = require("node:test"),
  { readFileSync } = require("node:fs"),
  path = require("node:path"),
  vm = require("node:vm"),
  { transformSync } = require("next/dist/build/swc");
const { hooks, jsx, all } = require("./resource-ui-harness.cjs"),
  {
    compile,
    catalogue,
    channels,
    stocks,
    contracts,
    response,
    settle,
    deferred,
  } = require("./resource-library-helpers.cjs");
const css = { __esModule: true, default: new Proxy({}, { get: (_, k) => k }) };
const translations = () => {
  const t = (key) => key;
  t.has = () => true;
  return t;
};
const runtime = { jsx, jsxs: jsx, Fragment: "fragment" };
const button = (tree, key) => all(tree, (n) => n.type === "button" && n.props.children === key)[0];
const loaded = (data) => ({ data, loading: false, error: "", stale: false });
test("reopening the same snapshot does not restart catalogue reads during the private-content gap", () => {
  const h = hooks(),
    calls = [],
    model = {
      owner: "A",
      authenticated: true,
      configured: true,
      reload: (source) => calls.push(source),
    };
  const ResourceLibrary = compile("../components/ResourceLibrary.tsx", {
    react: h.react,
    "react/jsx-runtime": runtime,
    "next-intl": { useTranslations: translations, useLocale: () => "en" },
    "./useResourceLibrary": { useResourceLibrary: () => model },
    "./AuthProvider": {
      useAuth: () => ({ status: "authenticated", sessionKey: model.owner, profile: {} }),
    },
    "@/lib/resource-library": contracts,
    "./ResourceLibrary.module.css": css,
  }).default;
  const render = (holdingsVersion) =>
    h.render(() => ResourceLibrary({ holdingsVersion, children: "HOLDINGS" }));
  render("snapshot_1");
  render(undefined);
  render("snapshot_1");
  assert.deepEqual(calls, []);
  render(undefined);
  render("snapshot_2");
  assert.deepEqual(calls, ["catalogue"]);
  render("snapshot_2");
  assert.deepEqual(calls, ["catalogue"]);
  h.close();
});

test("actual ResourceLibrary category selection drives real hook demand without blocking ready holdings or inventing channel data", async () => {
  const h = hooks(),
    calls = [],
    gate = deferred(),
    events = new Map();
  let owner = "owner_A:1",
    held = true,
    model;
  const auth = {
    useAuth: () => ({
      status: "authenticated",
      sessionKey: owner,
      profile: { uid: owner },
      agentHubConfigured: true,
      requestPrivate,
    }),
  };
  async function requestPrivate(service, route, key, options) {
    calls.push({ service, route, key, options });
    if (route.includes("catalogue")) return response(catalogue());
    if (route.endsWith("channel-follows")) return held ? gate.promise : response(channels());
    throw Error("Shared watchlist must not be fetched again");
  }
  const globals = {
    document: {
      visibilityState: "visible",
      addEventListener: (k, v) => events.set(k, v),
      removeEventListener: (k) => events.delete(k),
    },
    window: { setTimeout, clearTimeout },
  };
  const hook = compile(
    "../components/useResourceLibrary.ts",
    { react: h.react, "@/components/AuthProvider": auth, "@/lib/resource-library": contracts },
    globals,
  );
  const library = compile("../components/ResourceLibrary.tsx", {
    react: h.react,
    "react/jsx-runtime": runtime,
    "next-intl": { useTranslations: translations },
    "./useResourceLibrary": hook,
    "./AuthProvider": auth,
    "@/lib/resource-library": contracts,
    "./ResourceLibrary.module.css": css,
  });
  const props = {
    active: true,
    workspaceScope: "vault_A:1",
    watchlist: {
      sessionKey: "owner_A:1",
      items: stocks().items,
      limit: 50,
      loading: false,
      busy: false,
    },
    children: (m) =>
      jsx("p", {
        children:
          m.catalogue.data && !m.catalogue.loading && !m.catalogue.error && !m.catalogue.stale
            ? "HOLDINGS_READY"
            : "HOLDINGS_LOADING",
      }),
  };
  const render = () =>
    h.render(() => {
      const view = library.default(props);
      model = view.props.model;
      return library.ResourceLibraryView(view.props);
    });
  try {
    let tree = render();
    await settle();
    tree = render();
    assert.equal(
      all(tree, (n) => n.type === "p" && n.props.children === "HOLDINGS_READY").length,
      1,
    );
    assert.equal(model.follows.data, null);
    assert.equal(model.follows.loading, false);
    assert.equal(calls.filter((c) => c.route.endsWith("channel-follows")).length, 0);
    button(tree, "kinds.channel_follows").props.onClick();
    tree = render();
    assert.equal(model.follows.loading, true);
    assert.equal(model.follows.data, null);
    assert.equal(calls.filter((c) => c.route.endsWith("channel-follows")).length, 1);
    gate.resolve(response(channels()));
    await settle();
    tree = render();
    assert.equal(model.follows.data.items[0].name, "Synthetic Creator");
    button(tree, "kinds.holdings").props.onClick();
    tree = render();
    button(tree, "kinds.channel_follows").props.onClick();
    tree = render();
    await settle();
    assert.equal(calls.filter((c) => c.route.endsWith("channel-follows")).length, 1);
    owner = "owner_B:2";
    held = false;
    tree = render();
    await settle();
    tree = render();
    assert.equal(
      all(tree, (n) => n.type === "button" && n.props.children === "kinds.holdings")[0].props[
        "aria-pressed"
      ],
      true,
    );
    assert.equal(model.follows.data, null);
    assert.equal(
      calls.filter((c) => c.key === owner && c.route.endsWith("channel-follows")).length,
      0,
    );
  } finally {
    h.close();
  }
});
test("real category tabs reveal operative watchlist and follows, with shared-owner list identity and one reconnect read", async () => {
  const h = hooks(),
    edits = [],
    shared = {
      sessionKey: "A",
      items: stocks().items,
      loading: false,
      loaded: true,
      busy: false,
      reload: () => edits.push(["reload"]),
      limit: 50,
      add: (v) => edits.push(["add", v]),
      remove: (v) => edits.push(["remove", v]),
    };
  const { ResourceLibraryView } = compile("../components/ResourceLibrary.tsx", {
    react: h.react,
    "react/jsx-runtime": runtime,
    "next-intl": { useTranslations: translations, useLocale: () => "en" },
    "./useResourceLibrary": {},
    "./AuthProvider": {
      useAuth: () => ({ status: "authenticated", sessionKey: "A", profile: {} }),
    },
    "@/lib/resource-library": contracts,
    "./ResourceLibrary.module.css": css,
  });
  const model = {
    owner: "A",
    authenticated: true,
    configured: true,
    offline: false,
    canRefresh: true,
    catalogue: loaded(catalogue()),
    watchlist: loaded(stocks("WRONG")),
    follows: loaded(channels()),
    reload(source) {
      assert.notEqual(source, "watchlist", "Must not fetch a second copy of the shared watchlist");
    },
  };
  const render = () =>
    h.render(() => ResourceLibraryView({ model, watchlist: shared, children: "HOLDINGS" }));
  let tree = render();
  assert.ok(
    all(tree, (n) => n.type === "section" && n.props["aria-label"] === "kinds.holdings").length,
  );
  button(tree, "kinds.watchlist").props.onClick();
  tree = render();
  assert.ok(all(tree, (n) => n.type === "strong" && n.props.children === "SYNTH").length);
  assert.equal(all(tree, (n) => n.props?.children === "WRONG").length, 0);
  all(tree, (n) => n.type === "input")[0].props.onChange({ target: { value: "aapl" } });
  tree = render();
  all(tree, (n) => n.type === "form")[0].props.onSubmit({ preventDefault() {} });
  assert.deepEqual(edits, [["add", "AAPL"]]);
  button(render(), "remove").props.onClick();
  assert.deepEqual(edits[1], ["remove", "SYNTH"]);
  const watchlistRows = () => all(render(), (n) => n.props?.className === "watchlistRows")[0];
  assert.equal(watchlistRows().props["data-editable"], true);
  shared.busy = true;
  const pendingRows = watchlistRows();
  assert.equal(button(pendingRows, "remove").props.disabled, true);
  assert.equal(all(pendingRows, (n) => n.type === "strong")[0].props.children, "SYNTH");
  shared.busy = false;
  model.offline = true;
  model.canRefresh = false;
  tree = render();
  assert.equal(button(tree, "remove").props.disabled, true);
  assert.equal(button(tree, "retry").props.disabled, true);
  assert.ok(all(tree, (n) => n.type === "strong" && n.props.children === "SYNTH").length);
  button(tree, "kinds.holdings").props.onClick();
  model.offline = false;
  model.canRefresh = true;
  tree = render();
  assert.equal(edits.filter(([op]) => op === "reload").length, 0);
  button(tree, "kinds.watchlist").props.onClick();
  render();
  render();
  assert.equal(edits.filter(([op]) => op === "reload").length, 1);
  shared.error = "unavailable";
  tree = render();
  assert.equal(button(tree, "remove").props.disabled, true);
  button(tree, "retry").props.onClick();
  assert.equal(edits.filter(([op]) => op === "reload").length, 2);
  shared.error = "";
  assert.equal(Boolean(button(render(), "remove").props.disabled), false);
  shared.sessionKey = "B";
  assert.equal(all(render(), (n) => n.props?.children === "SYNTH").length, 0);
  h.close();
});
test("actual holdings chooser and drop zone share the importer; multiple files and blocked states never reach it", async () => {
  const h = hooks(),
    calls = [],
    ref = {
      kind: "holdings",
      sourceService: "portfolio",
      resourceId: "source",
      incarnation: "inc",
    };
  let model = {
    configured: true,
    authenticated: true,
    phase: "unlocked",
    canWriteState: true,
    busy: null,
    sources: [],
    newSource: true,
    importFile: (f) => calls.push(["import", f]),
    save: async (callback) => {
      calls.push(["save"]);
      if (callback) await callback({ resourceRef: ref });
    },
    selectAccounts() {},
  };
  const names = {
    enabled: true,
    rename: async (r, name, fresh) => {
      calls.push(["name", r, name, fresh]);
      return true;
    },
  };
  const source = readFileSync(path.join(__dirname, "../components/ResourcesPanel.tsx"), "utf8"),
    { code } = transformSync(source, {
      filename: "ResourcesPanel.tsx",
      jsc: {
        parser: { syntax: "typescript", tsx: true },
        target: "es2022",
        transform: { react: { runtime: "automatic" } },
      },
      module: { type: "commonjs" },
    });
  const imports = {
    "@/lib/holdings-facts": compile("../lib/holdings-facts.ts"),
    "@/lib/holdings-publication": compile("../lib/holdings-publication.ts", {
      "./resource-library": contracts,
    }),
    "./HoldingsEditor": { __esModule: true, default: () => null },
    "./HoldingsValuation": { __esModule: true, default: () => null },
    "next/dynamic": { __esModule: true, default: () => () => null },
    react: h.react,
    "react/jsx-runtime": runtime,
    "next-intl": { useTranslations: translations, useLocale: () => "en" },
    "./WorkspaceFeedback": { LoadingIndicator: () => null, InlineError: () => null },
    "@/components/useHoldingsWorkspace": {},
    "./ResourceLibrary": {},
    "./PasskeyHelp": {},
    "./useDisplayNames": {},
    "./HoldingsSourceBar": { HoldingsSourceBar: () => null },
    "./ResourcesPanel.module.css": css,
  };
  const module = { exports: {} };
  vm.runInNewContext(code + "\nmodule.exports.Workspace = Workspace;", {
    module,
    exports: module.exports,
    require: (name) => {
      assert.ok(name in imports, name);
      return imports[name];
    },
    requestAnimationFrame: (fn) => fn(),
  });
  const render = () => h.render(() => module.exports.Workspace({ model, names, library: {} }));
  const file = { name: "synthetic.csv" };
  let tree = render();
  const chooser = all(tree, (n) => n.type === "input" && n.props.type === "file")[0];
  chooser.props.onChange({ target: { files: [file], value: "name" } });
  let prevented = 0;
  all(tree, (n) => n.props["aria-label"] === "manage.dropZone")[0].props.onDrop({
    preventDefault() {
      prevented++;
    },
    dataTransfer: { files: [file] },
  });
  assert.equal(prevented, 1);
  assert.deepEqual(calls, [
    ["import", file],
    ["import", file],
  ]);
  all(tree, (n) => n.props["aria-label"] === "manage.dropZone")[0].props.onDrop({
    preventDefault() {},
    dataTransfer: { files: [file, file] },
  });
  assert.equal(calls.length, 2);
  model = { ...model, hasPending: true };
  tree = render();
  assert.equal(
    all(tree, (n) => n.type === "input" && n.props.type === "file")[0].props.disabled,
    true,
  );
  all(tree, (n) => n.props["aria-label"] === "manage.dropZone")[0].props.onDrop({
    preventDefault() {},
    dataTransfer: { files: [file] },
  });
  assert.equal(calls.length, 2);
  model = {
    ...model,
    hasPending: false,
    preview: {
      reportDate: null,
      accounts: [],
      stats: { accounts: 0, positions: 0, totals: {}, excluded: 0, duplicates: 0 },
      warnings: [],
      resourceContent: { data: { accounts: [], excludedAssets: [] } },
    },
  };
  tree = render();
  const input = all(tree, (n) => n.type === "input" && n.props.maxLength === 80)[0];
  input.props.onChange({ target: { value: "Named synthetic" } });
  tree = render();
  await button(tree, "confirmSave").props.onClick();
  assert.equal(calls.at(-2)[0], "save");
  assert.deepEqual(JSON.parse(JSON.stringify(calls.at(-1))), [
    "name",
    ref,
    "Named synthetic",
    true,
  ]);
  model = {
    ...model,
    phase: "unlocked",
    preview: null,
    error: "service_unavailable",
    readStored: async () => calls.push(["readStored"]),
    reload: async () => calls.push(["reload"]),
  };
  await button(render(), "reloadWorkspace").props.onClick();
  assert.deepEqual(
    calls.at(-1),
    ["readStored"],
    "unlocked holdings error retries the actual source read",
  );
  model.phase = "locked";
  await button(render(), "reloadWorkspace").props.onClick();
  assert.deepEqual(calls.at(-1), ["reload"], "locked recovery keeps its vault lifecycle path");
  h.close();
});

test("data settings open a smooth dialog, preserve original pending-name recovery and fresh scope controls", async () => {
  const h = hooks(),
    calls = [],
    ref = {
      kind: "holdings",
      sourceService: "portfolio",
      resourceId: "holdings",
      incarnation: "incarnation_A",
    };
  const { HoldingsSourceBar } = compile("../components/HoldingsSourceBar.tsx", {
    react: h.react,
    "react/jsx-runtime": runtime,
    "next-intl": { useTranslations: translations, useLocale: () => "en" },
    "./useTasks": {},
    "./ResourcesPanel.module.css": css,
  });
  let pending = false;
  const names = {
    scope: "A:root:1",
    ready: false,
    enabled: false,
    loading: true,
    name: () => "PRIVATE NAME",
    pending: () => pending,
    clearError() {},
    rename: async (r, name) => calls.push(["rename", r, name]),
    recover: async (r, replay) => calls.push(["recover", r, replay]),
  };
  const model = {
    sources: [{ resourceRef: ref, sourceEpoch: 1 }],
    selectedSourceId: ref.resourceId,
    canWriteState: true,
    phase: "unlocked",
    sourceMetadata: { state: "active", source: { resourceRef: ref, sourceEpoch: 1 } },
  };
  const render = () =>
    h.render(() =>
      HoldingsSourceBar({
        model,
        names,
        library: { catalogue: loaded(catalogue()) },
        onUpdate() {},
        children: "DANGER_CONFIRMATIONS",
      }),
    );
  let tree = render();
  const dialog = () => all(tree, (n) => n.props.id === "holdings-source-settings")[0];
  assert.equal(dialog().props.open, false);
  button(tree, "lifecycle.settings").props.onClick();
  tree = render();
  assert.equal(dialog().props.open, true);
  const input = all(tree, (n) => n.type === "input")[0];
  assert.equal(input.props.value, "PRIVATE NAME");
  assert.ok(!input.props.disabled);
  model.busy = "reading";
  input.props.onChange({ target: { value: "Renamed" } });
  tree = render();
  assert.equal(button(tree, "manage.saveName").props.disabled, true);
  all(tree, (n) => n.type === "form")[0].props.onSubmit({ preventDefault() {} });
  assert.deepEqual(calls, []);
  model.busy = null;
  tree = render();
  assert.equal(button(tree, "manage.saveName").props.disabled, false);
  all(tree, (n) => n.type === "form")[0].props.onSubmit({ preventDefault() {} });
  assert.deepEqual(calls[0], ["rename", ref, "Renamed"]);
  pending = true;
  tree = render();
  assert.equal(button(tree, "manage.saveName").props.disabled, true);
  button(tree, "manage.checkName").props.onClick();
  button(tree, "manage.retryNameSave").props.onClick();
  assert.equal(calls[1][2], undefined);
  assert.equal(calls[2][2], true);
  assert.ok(
    all(
      tree,
      (n) => n.type === "details" && n.props.children[0].props.children === "manage.advanced",
    ).length,
  );
  model.preview = { selectedAccountIds: [] };
  tree = render();
  assert.equal(
    button(tree, "lifecycle.settings").props.disabled,
    false,
    "account-scope review remains reachable during preview",
  );
  assert.equal(
    button(tree, "lifecycle.add").props.disabled,
    false,
    "preview can be saved as independent data",
  );
  h.close();
});

test("holdings choices hide confirmed deletion by source incarnation and retain pending recovery", () => {
  const h = hooks();
  const { HoldingsSourceBar } = compile("../components/HoldingsSourceBar.tsx", {
    react: h.react,
    "react/jsx-runtime": runtime,
    "next-intl": { useTranslations: translations, useLocale: () => "en" },
    "./useTasks": {},
    "./ResourcesPanel.module.css": css,
  });
  const data = catalogue();
  const holdings = data.groups.find((group) => group.kind === "holdings");
  const removed = holdings.items[0];
  const liveRef = { ...removed.ref, resourceId: "source_B", incarnation: "incarnation_B" };
  removed.state = "deleted";
  holdings.items.push(
    { ...removed, ref: { ...liveRef, incarnation: "incarnation_A" } },
    { ...removed, ref: liveRef, state: "active" },
  );
  const model = {
    sources: [
      { resourceRef: removed.ref, sourceEpoch: 1 },
      { resourceRef: liveRef, sourceEpoch: 1 },
    ],
    selectedSourceId: removed.ref.resourceId,
    canWriteState: true,
    phase: "unlocked",
    sourceMutation: null,
  };
  let read = { ...loaded(null), loading: true };
  const reloads = [];
  const render = () =>
    h.render(() =>
      HoldingsSourceBar({
        model,
        names: {
          scope: "A",
          name: (ref) => (ref === removed.ref ? "Removed name" : "Active name"),
          pending: () => false,
          clearError() {},
        },
        library: { catalogue: read, reload: (kind) => reloads.push(kind) },
        onUpdate() {},
        children: "PENDING_RECOVERY",
      }),
    );
  const options = (tree) => all(tree, (n) => n.type === "option").map((n) => n.props.children);
  let tree = render();
  assert.deepEqual(options(tree), [], "cold registration anchors never become options");
  assert.equal(button(tree, "lifecycle.settings"), undefined);
  assert.ok(all(tree, (n) => n.props.label === "loading").length);
  read = { ...loaded(data), stale: true, error: "source_unavailable" };
  tree = render();
  assert.deepEqual(options(tree), []);
  assert.ok(all(tree, (n) => n.props.children === "lifecycle.sourcesUnavailable").length);
  button(tree, "manage.refresh").props.onClick();
  assert.deepEqual(reloads, ["catalogue"]);

  read = loaded(data);
  model.sourceMutation = { action: "delete" };
  tree = render();
  assert.deepEqual(options(tree), ["lifecycle.choose", "Active name"]);
  assert.equal(button(tree, "lifecycle.settings"), undefined);
  assert.ok(tree.props.children.includes("PENDING_RECOVERY"));

  model.sourceMutation = null;
  tree = render();
  assert.deepEqual(options(tree), ["lifecycle.choose", "Active name"]);
  assert.equal(all(tree, (n) => n.type === "select")[0].props.value, "");
  assert.equal(all(tree, (n) => n.props.id === "holdings-source-settings")[0].props.open, false);

  model.sources.pop();
  holdings.items.length = 0;
  model.sourceMetadata = { state: "deleted", source: model.sources[0] };
  tree = render();
  assert.equal(all(tree, (n) => n.type === "select").length, 0);
  assert.ok(all(tree, (n) => n.props.children === "lifecycle.empty").length);
  assert.equal(button(tree, "lifecycle.add").props.disabled, false);
  h.close();
});

test("visible writable resource recovery reads one missing selected source per Owner/vault generation and never scans blocked views", () => {
  const h = hooks(),
    reads = [],
    source = {
      resourceRef: {
        kind: "holdings",
        sourceService: "portfolio",
        resourceId: "source_A",
        incarnation: "inc_A",
      },
      sourceEpoch: 1,
    };
  let model = {
    owner: "owner_A",
    authenticated: true,
    configured: true,
    phase: "unlocked",
    vault: { vaultId: "vault_A", version: 1 },
    vaultGeneration: 1,
    canWriteState: true,
    needsDeviceApproval: false,
    sources: [source],
    selectedSourceId: null,
    sourceMetadata: null,
    content: null,
    preview: null,
    importPreview: null,
    newSource: false,
    busy: null,
    error: "",
    readStored: async () =>
      reads.push([model.owner, model.vaultGeneration, model.selectedSourceId]),
  };
  const { default: ResourcesPanel } = compile("../components/ResourcesPanel.tsx", {
    react: h.react,
    "react/jsx-runtime": runtime,
    "next-intl": { useTranslations: translations },
    "next/dynamic": { __esModule: true, default: () => () => null },
    "@/components/useHoldingsWorkspace": {},
    "@/lib/holdings-facts": compile("../lib/holdings-facts.ts"),
    "./HoldingsEditor": { __esModule: true, default: () => null },
    "./ResourceLibrary": { __esModule: true, default: () => null },
    "./PasskeyHelp": {},
    "./HoldingsSourceBar": {},
    "./useDisplayNames": { useDisplayNames: () => ({ scope: "names" }) },
    "./ResourcesPanel.module.css": css,
  });
  const draw = (active = true) => {
    model = { ...model }; // The real workspace hook publishes an immutable render snapshot.
    return h.render(() => {
      const panel = ResourcesPanel({ workspace: model, active });
      return panel.type(panel.props);
    });
  };
  draw(false);
  assert.equal(reads.length, 0);
  for (const blocked of [
    { phase: "locked" },
    { canWriteState: false },
    { needsDeviceApproval: true },
    { configured: false },
    { sourceMetadata: { state: "active", snapshotId: null } },
    { content: { data: { snapshotId: "cached" } } },
    { preview: {} },
    { importPreview: {} },
    { newSource: true },
    { sourceReview: {} },
    { sourceMutation: {} },
    { staleSourceMutation: true },
    { sourceCreationId: "unfinished" },
    { hasPending: true },
    { uploadCancellation: {} },
    { uploadCancellationReview: {} },
    { busy: "reading" },
    { error: "service_unavailable" },
  ]) {
    const before = model;
    model = { ...before, ...blocked };
    draw();
    assert.equal(reads.length, 0, JSON.stringify(blocked));
    model = before;
  }
  draw();
  draw();
  assert.equal(reads.length, 1);
  model.error = "service_unavailable";
  draw();
  model.error = "";
  draw(false);
  draw();
  assert.equal(
    reads.length,
    1,
    "failed automatic reads never loop after reentry or error clearing",
  );
  model.sources = [
    source,
    { ...source, resourceRef: { ...source.resourceRef, resourceId: "source_B" } },
  ];
  model.selectedSourceId = "source_B";
  draw();
  assert.equal(reads.length, 2);
  model.vaultGeneration++;
  draw();
  assert.equal(reads.length, 3);
  model.owner = "owner_B";
  model.canWriteState = false;
  draw();
  assert.equal(reads.length, 3);
  model.canWriteState = true;
  draw();
  assert.equal(reads.length, 4);
  model.selectedSourceId = "source_A";
  model.content = { data: { snapshotId: "cached" } };
  draw();
  assert.equal(reads.length, 4);
  model.content = null;
  model.sourceMetadata = { state: "active", snapshotId: null };
  draw();
  assert.equal(reads.length, 4);
  model.sourceMetadata = null;
  model.sources = [];
  model.selectedSourceId = null;
  draw();
  assert.equal(reads.length, 4);
  h.close();
});
