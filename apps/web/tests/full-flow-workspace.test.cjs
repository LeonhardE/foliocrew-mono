const cacheContracts = require("./resource-library-helpers.cjs").compile(
  "../lib/workspace-cache.ts",
);
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const { transformSync } = require("next/dist/build/swc");
const {
  catalogue,
  channels,
  stocks,
  contracts: resourceContracts,
} = require("./resource-library-helpers.cjs");

const CONTRACT = "folioview.agent-workspace.v2.0";
const settle = () => new Promise((resolve) => setImmediate(resolve));
const clone = (value) => JSON.parse(JSON.stringify(value));
const response = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
function compile(file, imports = {}, globals = {}) {
  const filename = path.resolve(__dirname, file);
  const { code } = transformSync(readFileSync(filename, "utf8"), {
    filename,
    jsc: {
      parser: { syntax: "typescript", tsx: filename.endsWith("tsx") },
      target: "es2022",
      transform: { react: { runtime: "automatic" } },
    },
    module: { type: "commonjs" },
  });
  const module = { exports: {} };
  vm.runInNewContext(code, {
    module,
    exports: module.exports,
    require(name) {
      if (["@/lib/resource-display", "../resource-display"].includes(name))
        return require("./resource-library-helpers.cjs").compile("../lib/resource-display.ts");
      if (name === "../display-name-contract")
        return require("./resource-library-helpers.cjs").compile("../lib/display-name-contract.ts");
      if (name === "./WorkspacePanels")
        return require("./workspace-panel-helpers.cjs").panelStandins(imports);
      if (["./WorkspaceFeedback", "./ReportDialog"].includes(name))
        return require("./workspace-feedback-helpers.cjs").component(name, imports);
      if (name === "@/lib/workspace-cache") return cacheContracts;
      if (name === "@/lib/holdings-publication")
        return compile("../lib/holdings-publication.ts", {
          "./resource-library": resourceContracts,
        });
      assert.ok(Object.hasOwn(imports, name), "Unexpected flow import " + name);
      return imports[name];
    },
    Response,
    AbortController,
    TextEncoder,
    TextDecoder,
    Uint8Array,
    structuredClone,
    URLSearchParams,
    Intl,
    ...globals,
  });
  return module.exports;
}
function find(tree, predicate) {
  if (!tree || typeof tree !== "object") return null;
  if (Array.isArray(tree)) {
    for (const child of tree) {
      const found = find(child, predicate);
      if (found) return found;
    }
    return null;
  }
  return predicate(tree) ? tree : find(tree.props?.children, predicate);
}
function eventTarget() {
  const events = new Map();
  return {
    addEventListener(name, callback) {
      if (!events.has(name)) events.set(name, new Set());
      events.get(name).add(callback);
    },
    removeEventListener: (name, callback) => events.get(name)?.delete(callback),
    emit(name) {
      for (const callback of [...(events.get(name) || [])]) callback();
    },
  };
}
function hooks() {
  let index = 0;
  const cells = [],
    effects = [];
  const changed = (a, b) => !a || a.length !== b.length || b.some((v, n) => v !== a[n]);
  let dirty = false;
  const react = {
    useState(initial) {
      const slot = index++;
      cells[slot] ??= { value: typeof initial === "function" ? initial() : initial };
      return [
        cells[slot].value,
        (next) => {
          const value = typeof next === "function" ? next(cells[slot].value) : next;
          dirty ||= !Object.is(value, cells[slot].value);
          cells[slot].value = value;
        },
      ];
    },
    useRef(value) {
      const slot = index++;
      cells[slot] ??= { current: value };
      return cells[slot];
    },
    useCallback(callback, deps) {
      const slot = index++;
      if (!cells[slot] || changed(cells[slot].deps, deps)) cells[slot] = { deps, value: callback };
      return cells[slot].value;
    },
    useEffect(effect, deps) {
      const slot = index++;
      if (!cells[slot] || changed(cells[slot].deps, deps)) effects.push({ slot, effect, deps });
    },
  };
  return {
    react,
    run(action, flush = true) {
      let value;
      for (let n = 0; n < 20; n++) {
        dirty = false;
        index = 0;
        value = action();
        if (flush)
          for (const e of effects.splice(0)) {
            cells[e.slot]?.cleanup?.();
            cells[e.slot] = { deps: e.deps, cleanup: e.effect() };
          }
        if (!flush || !dirty) return value;
      }
      assert.fail("Flow hook effects did not settle");
    },
    close() {
      for (const cell of cells) cell?.cleanup?.();
    },
  };
}
/** Compose current workspace navigation with its real watchlist and resource hooks. */
function flow({
  hash = "",
  search = "",
  owner = "A:1",
  access = { ownerConfigStatus: "ready" },
  versionedWatchlist = false,
} = {}) {
  const pageHooks = hooks(),
    libraryHooks = hooks();
  const windows = eventTarget(),
    documents = eventTarget(),
    intervals = new Map(),
    timers = new Map();
  let serial = 0,
    active = "markets";
  const location = { origin: "http://localhost", pathname: "/", search, hash };
  const window = {
    ...windows,
    location,
    history: {
      pushState(_state, _title, value) {
        this.replaceState(_state, _title, value);
      },
      replaceState(_state, _title, value) {
        const url = new URL(value, location.origin);
        Object.assign(location, { pathname: url.pathname, search: url.search, hash: url.hash });
      },
    },
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    setTimeout(callback) {
      const id = ++serial;
      timers.set(id, callback);
      return id;
    },
    clearTimeout: (id) => timers.delete(id),
    setInterval(callback) {
      const id = ++serial;
      intervals.set(id, callback);
      return id;
    },
    clearInterval: (id) => intervals.delete(id),
  };
  const document = {
    ...documents,
    get visibilityState() {
      return "visible";
    },
  };
  const shared = {
    owner,
    authenticated: Boolean(owner),
    authStatus: owner ? "authenticated" : "anonymous",
    phase: owner ? "unlocked" : "anonymous",
    vaultGeneration: 1,
    vaultConfigured: true,
    canWriteState: false,
    stageLockedWatchlistAgentSync: async () => null,
    busy: null,
    error: "",
    lock() {
      shared.phase = "locked";
      shared.vaultGeneration++;
    },
  };
  const calls = [];
  const store = { A: { list: stocks(), revision: 1 } };
  const requestPrivate = async (service, route, sessionKey, options = {}) => {
    assert.equal(sessionKey, shared.owner, "Only the current owner may start a request");
    calls.push({ service, route, owner: sessionKey, options });
    const current = store[sessionKey.split(":")[0]];
    if (service === "user" && route.startsWith("/api/v1/watchlist")) {
      const [path, query] = route.split("?");
      const symbol = path.split("/").at(-1);
      if (options.method === "PUT") {
        current.list.items.push(stocks(symbol).items[0]);
        current.revision++;
      }
      if (options.method === "DELETE") {
        current.list.items = current.list.items.filter((row) => row.symbol !== symbol);
        current.revision++;
      }
      return response(
        versionedWatchlist && query === "includeRevision=true"
          ? { ...current.list, revision: current.revision }
          : current.list,
      );
    }
    if (route === "/api/v1/channel-follows") return response(channels());
    if (route === "/api/v2/resources/catalogue") return response(catalogue());
    return response({ code: "not_found" }, 404);
  };
  const auth = {
    useAuth: () => ({
      status: shared.authenticated ? "authenticated" : "anonymous",
      profile: shared.authenticated ? { uid: shared.owner?.split(":")[0] } : null,
      sessionKey: shared.owner,
      agentHubConfigured: true,
      requestPrivate,
    }),
  };
  const watchlistTypes = compile("../lib/watchlist.ts");
  const links = compile("../lib/inbox-link.ts", {}, { window });
  const useWatchlist = compile(
    "../components/useWatchlist.ts",
    {
      react: pageHooks.react,
      "@/components/AuthProvider": auth,
      "@/lib/watchlist": watchlistTypes,
    },
    { window },
  ).useWatchlist;
  const useResourceLibrary = compile(
    "../components/useResourceLibrary.ts",
    {
      react: libraryHooks.react,
      "@/components/AuthProvider": auth,
      "@/lib/resource-library": resourceContracts,
    },
    { window, document },
  ).useResourceLibrary;
  const jsx = (type, props, key) => ({ type, props, key });
  const ResourcePanel = () => null,
    TasksPanel = () => null,
    AgentsPanel = () => null,
    Sidebar = () => null,
    WatchlistAction = () => null;
  const marketReads = [];
  const noData = () => ({ data: null, loading: false, hasSettled: true, error: "" });
  const Dashboard = compile(
    "../components/WorkspaceShell.tsx",
    {
      react: pageHooks.react,
      "next/navigation": {
        usePathname: () => location.pathname,
        useRouter: () => {
          throw new Error("Workspace routes must not request a new server build");
        },
      },
      "./AuthProvider": { useAuth: () => access },
      "./useWorkspaceJourney": { useWorkspaceJourney: () => () => {} },
      "@/lib/workspace-routes": compile("../lib/workspace-routes.ts"),
      "react/jsx-runtime": { jsx, jsxs: jsx },
      "next-intl": { useLocale: () => "en", useTranslations: () => (key) => key },
      "./PersistentAgentsPanel": { PersistentAgentsPanel: AgentsPanel },
      "./IndependentAgentPanel": { IndependentAgentPanel: () => null },
      "./useIndependentAgent": { useIndependentAgent: () => ({ configuration: null }) },
      "./PersistentInboxPanel": { PersistentInboxPanel: () => null },
      "./usePersistentWorkspace": { usePersistentWorkspace: () => ({ enabled: false, views: [] }) },
      "./useAgentLinkConfiguration": { useAgentLinkConfiguration: () => ({ data: null }) },
      "@/components/PreferencesProvider": {
        usePreferences: () => ({ preferences: { defaultChartRange: "1m" }, resolvedTheme: "dark" }),
      },
      "@/components/SettingsPanel": { __esModule: true, default: () => null },
      "@/components/ResourcesPanel": { __esModule: true, default: ResourcePanel },
      "@/components/TasksPanel": { __esModule: true, default: TasksPanel },
      "@/components/AgentsPanel": { __esModule: true, default: AgentsPanel },
      "@/components/useHoldingsWorkspace": { useHoldingsWorkspace: () => shared },
      "@/lib/holdings-publication": require("./resource-library-helpers.cjs").compile(
        "../lib/holdings-publication.ts",
      ),
      "@/lib/ui-messages": { localizeMessage: (message) => message ?? "" },
      "@/lib/inbox-link": links,
      "@/components/CandlestickChart": { CandlestickChart: () => null },
      "@/components/InstrumentMetrics": { InstrumentMetrics: () => null },
      "@/components/FxRatesPanel": { __esModule: true, default: () => null },
      "@/components/WorkspaceSidebar": { WorkspaceSidebar: Sidebar },
      "@/components/useCachedMarketResource": {
        useCachedMarketResource(url) {
          if (url) marketReads.push(url);
          return noData();
        },
      },
      "@/components/useMarketResource": { useMarketResource: noData },
      "@/components/PersonalWatchlist": { PersonalWatchlist: () => null, WatchlistAction },
      "@/components/useWatchlist": { useWatchlist },
      "@/components/useWatchlistQuotes": { useWatchlistQuotes: () => ({ quotes: {} }) },
      "@/components/WatchlistNotification": { WatchlistNotification: () => null },
      "@/lib/market-data": compile("../lib/market-data.ts"),
    },
    { window },
  ).default;
  let page, resources;
  const render = (flush = true) => {
    page = pageHooks.run(() => Dashboard(), flush);
    active = find(page, (n) => n.type === Sidebar).props.activeView;
    resources = libraryHooks.run(
      () => useResourceLibrary({ active: active === "resources" }),
      flush,
    );
    return { page, resources, active };
  };
  return {
    shared,
    calls,
    location,
    marketReads,
    links,
    render,
    async ready() {
      render();
      await settle();
      return render();
    },
    async settle() {
      render();
      await settle();
      render();
      await settle();
      return render();
    },
    navigate(view) {
      find(page, (n) => n.type === Sidebar).props.onNavigate(view);
      return render();
    },
    panel(type) {
      return find(
        page,
        (n) =>
          n.type ===
          {
            resources: ResourcePanel,
            tasks: TasksPanel,
            agents: AgentsPanel,
            watchlist: WatchlistAction,
          }[type],
      ).props;
    },
    link(value, event = "hashchange") {
      location.hash = value;
      windows.emit(event);
      return render();
    },
    close() {
      pageHooks.close();
      libraryHooks.close();
      assert.equal(intervals.size, 0);
    },
  };
}

test("reloading a private route waits for access without showing or fetching Markets", () => {
  for (const path of ["/settings", "/agents", "/resources", "/tasks", "/inbox"]) {
    const access = {
      ownerConfigStatus: "loading",
      privateWorkspaceAvailable: false,
      status: "loading",
    };
    const h = flow({ access, owner: null });
    h.location.pathname = path;
    const market = (page) => find(page, (n) => n.props?.className === "market-view");
    const mountedPanel = (page) =>
      find(
        page,
        (n) => n.props?.className === "workspace-page" && !n.props.hidden && n.props.children,
      );
    for (const [ownerConfigStatus, status] of [
      ["loading", "loading"],
      ["loading", "anonymous"],
      ["ready", "verifying"],
    ]) {
      Object.assign(access, { ownerConfigStatus, status });
      const { page, active } = h.render();
      assert.equal(active, path === "/inbox" ? "tasks" : path.slice(1));
      assert.equal(market(page).props.hidden, true);
      assert.equal(mountedPanel(page), null);
      assert.ok(find(page, (n) => n.props?.children === "account.checking"));
    }
    Object.assign(access, { privateWorkspaceAvailable: true, status: "authenticated" });
    const { page } = h.render();
    assert.ok(mountedPanel(page));
    assert.equal(market(page).props.hidden, true);
    assert.deepEqual(h.marketReads, []);
    assert.equal(h.location.pathname, path);
    h.close();
  }
});

test("public result links are closed canonical fragments and OAuth handoff retains priority", async () => {
  const h = flow({ owner: null });
  assert.deepEqual(clone(h.links.readInboxResultLink("#inbox/result/result_A/revisions/2")), {
    resultId: "result_A",
    revision: 2,
  });
  for (const hash of [
    "#inbox/result/r\n",
    "#inbox/result/r\r\n",
    "#inbox/result/r/revisions/01",
    "#inbox/result/r/revisions/33",
    "#inbox/result/r?owner=A",
    "#inbox/result/%2fsecret",
    "#inbox/result/r/../x",
    "https://example.test/#inbox/result/r",
  ])
    assert.equal(h.links.readInboxResultLink(hash), null, hash);
  assert.equal(h.links.readInboxResultLink("#inbox/result/r\n/revisions/1"), null);
  assert.equal(h.render().active, "markets");
  h.location.search = "?native_request=request_synthetic&native_nonce=nonce_synthetic";
  assert.equal(h.link("#inbox/result/result_A1").active, "agents");
  await h.settle();
  assert.ok(h.calls.every(({ route }) => !route.startsWith("/api/v2/results")));
  h.close();
});

test("Market edits and resource discovery use the same owner source through the task and agent navigation", async () => {
  const h = flow();
  await h.ready();
  const originalWorkspace = h.shared;
  await h.panel("watchlist").watchlist.add("ADDED");
  await h.settle();
  h.navigate("resources");
  let state = await h.settle();
  assert.deepEqual(clone(state.resources.watchlist.data.items.map((row) => row.symbol)), [
    "SYNTH",
    "ADDED",
  ]);
  assert.deepEqual(clone(h.panel("watchlist").watchlist.items.map((row) => row.symbol)), [
    "SYNTH",
    "ADDED",
  ]);
  for (const group of state.resources.catalogue.data.groups) {
    state.resources.useForTask(group.items[0], h.panel("resources").onCreateTask);
    assert.equal(h.render().active, "tasks");
    const request = h.panel("tasks").request;
    assert.equal(request.owner, "A:1");
    assert.equal(request.binding.ref.kind, group.kind);
    assert.equal(h.panel("tasks").workspace, originalWorkspace);
    h.navigate("resources");
    state = await h.settle();
  }
  h.navigate("agents");
  assert.equal(h.panel("agents").workspace, originalWorkspace);
  h.navigate("inbox");
  await h.settle();
  assert.equal(h.shared, originalWorkspace);
  h.navigate("markets");
  assert.equal(h.render().active, "markets");
  h.close();
});

test("Market and Resources hand the same versioned watchlist to the existing vault after unlock", async () => {
  const h = flow({
    versionedWatchlist: true,
    access: {
      agentHubConfigured: true,
      ownerConfigStatus: "ready",
      status: "authenticated",
      sessionKey: "A:1",
    },
  });
  const markers = [];
  h.shared.loadHoldingsAgentSync = async () => [];
  h.shared.loadChannelFollowsAgentSync = async () => null;
  h.shared.loadWatchlistAgentSync = async () => null;
  h.shared.updateWatchlistAgentSync = async (vault, marker, stage) =>
    markers.push([vault, marker, stage]);
  h.shared.phase = "locked";
  await h.ready();
  await h.panel("watchlist").watchlist.add("ADDED");
  await h.settle();
  assert.deepEqual(markers, []);
  assert.deepEqual(
    h.calls.map(({ route }) => route),
    ["/api/v1/watchlist?includeRevision=true", "/api/v1/watchlist/ADDED?includeRevision=true"],
  );
  h.shared.vault = { vaultId: "vault_A" };
  h.shared.phase = "unlocked";
  h.shared.vaultGeneration++;
  h.navigate("resources");
  await h.settle();
  assert.deepEqual(clone(markers), [["vault_A", { revision: 2, confirmed: true }, true]]);
  assert.equal(h.panel("resources").watchlist.revision, 2);
  await h.panel("resources").watchlist.remove("ADDED");
  await h.settle();
  assert.deepEqual(clone(markers.slice(1)), [
    ["vault_A", { revision: 3, confirmed: false }, true],
    ["vault_A", { revision: 3, confirmed: true }, true],
  ]);
  assert.equal(h.panel("watchlist").watchlist.revision, 3);
  h.close();
});

test("locked Market saves only an acknowledgement and cannot attach it to a different vault", async () => {
  const h = flow({
    versionedWatchlist: true,
    access: {
      agentHubConfigured: true,
      ownerConfigStatus: "ready",
      status: "authenticated",
      sessionKey: "A:1",
    },
  });
  const staged = [];
  const promoted = [];
  h.shared.vault = { vaultId: "vault_A" };
  h.shared.phase = "locked";
  h.shared.stageLockedWatchlistAgentSync = async (owner, revision, vault, signal) => {
    staged.push([owner, revision, vault]);
    assert.equal(signal.aborted, false);
    return null;
  };
  h.shared.loadHoldingsAgentSync = async () => [];
  h.shared.loadChannelFollowsAgentSync = async () => null;
  h.shared.loadWatchlistAgentSync = async () => null;
  h.shared.updateWatchlistAgentSync = async (...args) => promoted.push(args);
  await h.ready();
  await h.panel("watchlist").watchlist.add("ADDED");
  await h.settle();
  assert.deepEqual(staged, [["A:1", 2, "vault_A"]]);
  assert.deepEqual(promoted, []);
  assert.deepEqual(
    h.calls.map(({ route }) => route),
    ["/api/v1/watchlist?includeRevision=true", "/api/v1/watchlist/ADDED?includeRevision=true"],
  );
  h.shared.vault = { vaultId: "vault_B" };
  h.shared.phase = "unlocked";
  h.shared.vaultGeneration++;
  h.navigate("resources");
  await h.settle();
  assert.deepEqual(promoted, []);
  h.close();
});

test("Market persists the acknowledged revision when the vault locks during a save", async () => {
  const h = flow({
    versionedWatchlist: true,
    access: {
      agentHubConfigured: true,
      ownerConfigStatus: "ready",
      status: "authenticated",
      sessionKey: "A:1",
    },
  });
  const staged = [];
  h.shared.vault = { vaultId: "vault_A" };
  h.shared.stageLockedWatchlistAgentSync = async (owner, revision, vault) => {
    staged.push([owner, revision, vault]);
    return vault;
  };
  h.shared.loadHoldingsAgentSync = async () => [];
  h.shared.loadChannelFollowsAgentSync = async () => null;
  h.shared.loadWatchlistAgentSync = async () => null;
  h.shared.updateWatchlistAgentSync = async (_vault, marker) => {
    if (!marker.confirmed) return;
    h.shared.lock();
    throw new Error("locked");
  };
  await h.ready();
  await h.panel("watchlist").watchlist.add("ADDED");
  await h.settle();
  assert.deepEqual(staged, [["A:1", 2, "vault_A"]]);
  assert.deepEqual(
    h.calls.map(({ route }) => route),
    ["/api/v1/watchlist?includeRevision=true", "/api/v1/watchlist/ADDED?includeRevision=true"],
  );
  h.close();
});

test("first-load Agent and Inbox handoffs wait for parent router setup and ignore a disposed mount", async () => {
  for (const [options, expected] of [
    [{ search: "?native_request=synthetic_request&native_nonce=" + "n".repeat(43) }, "/agents"],
    [{ hash: "#inbox/result/synthetic_result/revisions/1" }, "/tasks"],
  ]) {
    const h = flow({ ...options, owner: null });
    h.render();
    assert.equal(h.location.pathname, "/", "History cannot change during the initial child effect");
    await h.settle();
    assert.equal(h.location.pathname, expected);
    assert.equal(h.render().active, expected.slice(1));
    assert.ok(h.calls.every(({ route }) => !route.startsWith("/api/v2/results")));
    h.close();
  }
  const h = flow({
    owner: null,
    search: "?native_request=synthetic_request&native_nonce=" + "n".repeat(43),
  });
  h.render();
  h.close();
  await settle();
  assert.equal(h.location.pathname, "/");
});
