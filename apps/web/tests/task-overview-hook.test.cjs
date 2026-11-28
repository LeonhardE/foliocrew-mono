const test = require("node:test"),
  assert = require("node:assert/strict");
const { compile } = require("./resource-library-helpers.cjs"),
  { hooks, jsx, all } = require("./resource-ui-harness.cjs");
const { types, overview, reader, inbox, providers } = require("./task-overview-helpers.cjs"),
  fixtures = require("./task-overview-fixtures.cjs");
const tick = () => new Promise((r) => setImmediate(r));
function harness({
  count = 2,
  respond,
  open,
  overviewEnabled = true,
  readDetail,
  timers,
  userVault = false,
} = {}) {
  const ui = hooks(),
    calls = [],
    opens = [],
    events = new Map(),
    docEvents = new Map();
  let owner = "owner_A",
    active = true,
    visible = true,
    clock = Date.now(),
    current;
  class Clock extends Date {
    static now() {
      return clock;
    }
  }
  const workspace = {
    authenticated: true,
    owner,
    phase: "unlocked",
    vaultConfigured: true,
    vaultGeneration: 1,
    canWriteState: true,
    needsDeviceApproval: false,
    vault: { vaultId: "vault_A", version: 1 },
    listTaskDrafts: async () => [],
    listTaskOutbox: async () => [],
    openTask: async (p) => {
      opens.push(p.metadata.taskId);
      return open ? open(p) : { name: `Name ${p.metadata.taskId}` };
    },
  };
  const requestPrivate = async (service, path, key, options = {}) => {
    calls.push({ service, path, key, options });
    const custom = respond?.(path, options);
    if (custom !== undefined) return custom;
    const full = fixtures.body(options.json?.knownPacketVersions ? options.json : undefined, count);
    if (path.endsWith("/overview/query")) return Response.json(full);
    if (path === types.TASK_PACKET_QUERY)
      return Response.json(fixtures.batch(options.json.taskIds, full.tasks.items));
    if (path.includes("/tasks?")) return Response.json(full.tasks);
    if (path.endsWith("/persistent-connections")) return Response.json(full.connections);
    if (path.includes("persistent-results")) return Response.json(full.feeds.persistent);
    if (path.includes("results?"))
      return Response.json(path.includes("archived") ? full.feeds.archived : full.feeds.foreground);
    if (path.endsWith("capabilities")) return Response.json(full.capabilities);
    throw Error(`unexpected ${path}`);
  };
  const auth = {
    useAuth: () => ({
      status: "authenticated",
      profile: { uid: "uid_A" },
      sessionKey: owner,
      agentHubConfigured: true,
      ownerCapabilities: { userVault },
      requestPrivate,
    }),
  };
  const window = {
    location: { hash: "", pathname: "/tasks", search: "" },
    history: { replaceState() {} },
    setTimeout: timers?.setTimeout ?? setTimeout,
    clearTimeout: timers?.clearTimeout ?? clearTimeout,
    addEventListener: (n, f) => events.set(n, f),
    removeEventListener: (n) => events.delete(n),
  };
  const document = {
    get visibilityState() {
      return visible ? "visible" : "hidden";
    },
    addEventListener: (n, f) => {
      if (!docEvents.has(n)) docEvents.set(n, new Set());
      docEvents.get(n).add(f);
    },
    removeEventListener: (n, f) => docEvents.get(n)?.delete(f),
  };
  const globals = {
    window,
    document,
    Date: Clock,
    setTimeout: timers?.setTimeout ?? setTimeout,
    clearTimeout: timers?.clearTimeout ?? clearTimeout,
    setInterval,
    clearInterval,
    crypto: require("node:crypto").webcrypto,
  };
  const localOverview = compile(
    "../lib/task-overview.ts",
    {
      "./inbox-types": require("./task-overview-helpers.cjs").inbox,
      "./task-types": types,
      "./task-overview-request": require("./task-overview-helpers.cjs").request,
      "./task-result-reader": reader,
      "./report-provider-attribution": providers,
      "./workspace-cache": compile("../lib/workspace-cache.ts"),
    },
    globals,
  );
  const tasks = compile(
    "../components/useTasks.ts",
    {
      react: ui.react,
      "@/components/AuthProvider": auth,
      "@/lib/task-overview": localOverview,
      "@/lib/task-types": types,
      "@/lib/task-forms": compile("../lib/task-forms.ts", { "./task-types": types }),
    },
    globals,
  );
  const center = compile(
    "../components/useTaskCenter.ts",
    { react: ui.react, "./AuthProvider": auth },
    globals,
  );
  const results = compile(
    "../components/useTaskResults.ts",
    {
      react: ui.react,
      "./AuthProvider": auth,
      "@/lib/report-provider-attribution": providers,
      "@/lib/inbox-link": { readInboxResultLink: () => null, clearInboxResultLink() {} },
      "@/lib/inbox-types": inbox,
      "@/lib/task-result-reader": reader,
    },
    globals,
  );
  const t = (key) => key;
  t.has = () => false;
  const view = compile(
    "../components/TaskCenterPanel.tsx",
    {
      react: ui.react,
      "react/jsx-runtime": { jsx, jsxs: jsx },
      "next-intl": { useLocale: () => "en", useTranslations: () => t },
      "@/lib/task-forms": compile("../lib/task-forms.ts", { "./task-types": types }),
      "@/lib/task-center-schedule": { nextCenterOccurrence: () => null },
      "@/lib/task-types": types,
      "./ReportDialog": { ReportDialog: () => null },
      "./WorkspaceFeedback": { InlineError: () => null, LoadingIndicator: () => null },
      "./TaskCenterPanel.module.css": { __esModule: true, default: {} },
    },
    globals,
  );
  const render = () =>
    ui.render(() => {
      const m = tasks.useTasks(workspace, {
        active,
        catalogueOnDemand: true,
        overview: overviewEnabled,
        readDetail,
      });
      const c = center.useTaskCenter(
        workspace,
        active,
        m.opening ?? m.selected,
        m.overview,
        m.selectedDetail,
        Boolean(m.selected && m.form && !m.opening),
      );
      const observed = Object.values(c.manual)
        .flatMap((rows) =>
          rows.flatMap(
            (row) => row.snapshot?.executors?.map((e) => e.resultId).filter(Boolean) ?? [],
          ),
        )
        .sort()
        .join("|");
      const r = results.useTaskResults(workspace, undefined, m, active, observed, c, m.overview);
      const tree = view.TaskCenterView({ workspace, model: m, center: c, resultState: r, active });
      return (current = { m, c, r, tree });
    });
  return {
    workspace,
    calls,
    requestPrivate,
    opens,
    render,
    async ready() {
      for (let i = 0; i < 8; i++) {
        render();
        await tick();
      }
      return render();
    },
    active(v) {
      active = v;
      return render();
    },
    owner(v) {
      owner = v;
      workspace.owner = v;
      workspace.vaultGeneration++;
      return render();
    },
    advance(ms) {
      clock += ms;
    },
    hide(v) {
      visible = !v;
      for (const set of docEvents.values()) for (const f of [...set]) f();
      return render();
    },
    close() {
      ui.close();
    },
    get current() {
      return current;
    },
  };
}
test("opening a task verifies the fresh included packet without fetching its head twice", async () => {
  const h = harness({
    open: async (packet) => ({
      ...compile("../lib/task-forms.ts", { "./task-types": types }).defaultTask("custom"),
      name: "Synthetic " + packet.metadata.taskId,
      goal: "Review the synthetic portfolio",
    }),
    respond: (path) => {
      if (path === "/api/v2/tasks/task_1")
        return Response.json(fixtures.packet(fixtures.metadata(1)));
      if (path.endsWith("/tasks/task_1/manual")) return Response.json({ items: [] });
      if (path.endsWith("/tasks/task_1"))
        return Response.json({
          taskId: "task_1",
          taskVersion: 1,
          executionEpoch: 1,
          rules: null,
          assignments: [],
        });
    },
  });
  try {
    const x = await h.ready();
    h.workspace.loadTaskCenterPending = async () => null;
    h.workspace.verifyTaskCenterState = async (state) => state;
    h.workspace.refreshVault = async () => h.workspace.vault;
    await x.m.openTask("task_1");
    assert.equal(h.render().m.selected?.taskId, "task_1");
    assert.equal(h.calls.filter((c) => c.path === "/api/v2/tasks/task_1").length, 0);
    h.advance(30_001);
    await h.render().m.openTask("task_1");
    assert.equal(h.calls.filter((c) => c.path === "/api/v2/tasks/task_1").length, 1);
  } finally {
    h.close();
  }
});

test("three real task hooks share one overview and inline names preserve true unread/provider attribution", async () => {
  const h = harness();
  try {
    const { m, c, r } = await h.ready();
    assert.equal(h.calls.length, 1);
    assert.ok(h.calls[0].path.endsWith("/overview/query"));
    assert.equal(h.calls[0].options.json.packetLimit, 4);
    assert.equal(h.opens.length, 2);
    assert.equal(m.listReady, true);
    assert.equal(Object.keys(m.taskNames).length, 2);
    assert.equal(c.capabilityState, "ready");
    assert.equal(r.complete, true);
    assert.equal(h.current.tree.props["data-load-state"], "ready");
    assert.equal(r.unreadCounts.task_1, 1);
    assert.equal(
      r.providerFor({ kind: "persistent", metadata: fixtures.body().feeds.persistent.items[0] }),
      "muse",
    );
  } finally {
    h.close();
  }
});
test("fresh route reentry uses zero requests and expired reentry sends known names without a new packet read", async () => {
  const h = harness();
  try {
    await h.ready();
    h.active(false);
    h.active(true);
    await h.ready();
    assert.equal(h.calls.length, 1);
    h.active(false);
    h.advance(30001);
    h.active(true);
    await h.ready();
    assert.equal(h.calls.length, 2);
    assert.equal(h.calls[1].options.json.knownPacketVersions.length, 2);
    assert.equal(h.opens.length, 2);
  } finally {
    h.close();
  }
});
test("explicit list refresh takes one request and persistent report refresh takes two", async () => {
  const h = harness();
  try {
    let x = await h.ready();
    let start = h.calls.length;
    await x.m.reloadTasks();
    await h.ready();
    assert.equal(h.calls.length - start, 1);
    start = h.calls.length;
    await h.current.r.reload();
    await h.ready();
    assert.equal(h.calls.length - start, 2);
    assert.equal(h.calls.filter((c) => c.path.endsWith("/overview/query")).length, 1);
  } finally {
    h.close();
  }
});
test("budget null falls back only to the original packet query and slow local verification cannot finish names", async () => {
  const releases = [];
  const h = harness({
    respond: (path, o) => {
      if (path.endsWith("/overview/query")) {
        const b = fixtures.body(o.json);
        b.packets = null;
        return Response.json(b);
      }
    },
    open: (p) => new Promise((r) => releases.push(() => r({ name: `Name ${p.metadata.taskId}` }))),
  });
  try {
    let x = await h.ready();
    assert.equal(h.calls.length, 2);
    assert.equal(releases.length, 1);
    assert.equal(Object.keys(x.m.taskNames).length, 0);
    releases.shift()();
    await h.ready();
    releases.shift()();
    x = await h.ready();
    assert.equal(Object.keys(x.m.taskNames).length, 2);
    assert.equal(h.calls.length, 2);
  } finally {
    releases.forEach((f) => f());
    h.close();
  }
});
module.exports = { harness };

test("thirty-two names retain two verification workers and fetch only the seven non-inline four-packet suffixes", async () => {
  const h = harness({ count: 32 });
  try {
    let x = await h.ready();
    for (let i = 0; i < 16 && Object.keys(x.m.taskNames).length < 32; i++) x = await h.ready();
    assert.equal(Object.keys(x.m.taskNames).length, 32);
    assert.equal(h.opens.length, 32);
    assert.equal(h.calls.filter((c) => c.path === types.TASK_PACKET_QUERY).length, 7);
    assert.equal(h.calls.length, 8);
  } finally {
    h.close();
  }
});
test("receipt replay cannot extend freshness and new tasks are included despite all earlier names being known", async () => {
  let count = 2;
  const h = harness({
    respond: (path, o) =>
      path.endsWith("/overview/query") ? Response.json(fixtures.body(o.json, count)) : undefined,
  });
  try {
    await h.ready();
    for (let i = 0; i < 2; i++) {
      h.active(false);
      h.advance(10000);
      h.active(true);
      await h.ready();
    }
    assert.equal(h.calls.length, 1);
    count = 3;
    h.active(false);
    h.advance(11000);
    h.active(true);
    const x = await h.ready();
    assert.equal(h.calls.length, 2);
    assert.equal(h.calls[1].options.json.packetLimit, 4);
    assert.equal(h.calls[1].options.json.knownPacketVersions.length, 2);
    assert.equal(Object.keys(x.m.taskNames).length, 3);
    assert.equal(h.opens.length, 3);
  } finally {
    h.close();
  }
});
test("a bad nested packet rejects the entire overview before metadata capabilities feeds or names can complete", async () => {
  const h = harness({
    respond: (path, o) => {
      if (path.endsWith("/overview/query")) {
        const b = fixtures.body(o.json);
        b.packets.items[1].packet.metadata.taskId = "foreign_task";
        return Response.json(b);
      }
    },
  });
  try {
    const x = await h.ready();
    assert.equal(h.calls.length, 1);
    assert.equal(x.m.listReady, false);
    assert.equal(x.c.capabilityState, "error");
    assert.equal(x.r.ready, false);
    assert.notEqual(x.tree.props["data-load-state"], "ready");
    assert.equal(h.opens.length, 0);
  } finally {
    h.close();
  }
});
test("a feed cursor preserves partial real unread totals and all other cursors remain independent", async () => {
  const h = harness({
    respond: (path, o) => {
      if (path.endsWith("/overview/query")) {
        const b = fixtures.body(o.json);
        b.feeds.persistent.nextCursor = "pidx_" + "a".repeat(64) + ":1";
        return Response.json(b);
      }
    },
  });
  try {
    const x = await h.ready();
    assert.equal(x.r.ready, true);
    assert.equal(x.r.complete, false);
    assert.equal(x.r.partial, true);
    assert.notEqual(x.tree.props["data-load-state"], "ready");
    assert.equal(x.r.unreadCounts.task_1, 1);
    assert.equal(h.calls.length, 1);
    assert.equal(x.m.listReady, true);
  } finally {
    h.close();
  }
});
test("late overview responses cannot publish across an Owner switch or a hidden generation", async () => {
  for (const boundary of ["owner", "hidden"]) {
    let release,
      calls = 0;
    const gate = new Promise((r) => (release = r));
    const h = harness({
      respond: (path) =>
        path.endsWith("/overview/query")
          ? ++calls === 1
            ? gate
            : new Promise(() => {})
          : undefined,
    });
    try {
      h.render();
      await tick();
      assert.equal(h.calls.length, 1);
      if (boundary === "owner") h.owner("owner_B");
      else h.hide(true);
      release(Response.json(fixtures.body()));
      const x = await h.ready();
      assert.equal(x.m.listReady, false);
      assert.equal(x.r.ready, false);
      assert.equal(h.opens.length, 0);
    } finally {
      h.close();
    }
  }
});
test("slow original Worker verification remains globally bounded to two and cannot signal complete names", async () => {
  const releases = [];
  const h = harness({
    count: 8,
    open: (p) => new Promise((r) => releases.push(() => r({ name: p.metadata.taskId }))),
  });
  try {
    const x = await h.ready();
    assert.equal(releases.length, 2);
    assert.equal(Object.keys(x.m.taskNames).length, 0);
    assert.equal(x.m.loading, false);
    assert.equal(x.r.complete, true);
    assert.equal(x.tree.props["data-load-state"], "loading");
    assert.equal(h.calls.filter((c) => c.path.endsWith("/overview/query")).length, 1);
  } finally {
    h.active(false);
    releases.forEach((f) => f());
    await tick();
    h.close();
  }
});

function controlledTimers() {
  const pending = new Map();
  let now = 0;
  return {
    setTimeout(callback, delay) {
      const id = {};
      pending.set(id, { at: now + delay, callback });
      return id;
    },
    clearTimeout(id) {
      pending.delete(id);
    },
    advance(to) {
      now = to;
      for (const [id, timer] of pending) {
        if (timer.at > now) continue;
        pending.delete(id);
        timer.callback();
      }
    },
  };
}

test("a cold overview finishing after 12.7s reaches task names, run capabilities and reports in one read", async () => {
  const timers = controlledTimers(),
    gate = Promise.withResolvers();
  const h = harness({
    timers,
    respond: (path) => (path.endsWith("/overview/query") ? gate.promise : undefined),
  });
  try {
    await h.ready();
    timers.advance(12_788);
    let x = await h.ready();
    assert.equal(h.calls[0].options.signal.aborted, false);
    assert.equal(x.m.loading, true);
    assert.equal(x.m.listError, "");
    gate.resolve(Response.json(fixtures.body()));
    x = await h.ready();
    assert.equal(x.tree.props["data-load-state"], "ready");
    assert.equal(x.c.enabled, true);
    assert.equal(x.r.unreadCounts.task_1, 1);
    assert.equal(h.calls.length, 1);
  } finally {
    h.close();
  }
});

test("a late proxy 503 leaves time for the list fallback", async () => {
  const timers = controlledTimers(),
    overview = Promise.withResolvers(),
    list = Promise.withResolvers();
  const h = harness({
    timers,
    respond: (path) => {
      if (path.endsWith("/overview/query")) return overview.promise;
      if (path.includes("/tasks?")) return list.promise;
    },
  });
  try {
    await h.ready();
    timers.advance(20_100);
    overview.resolve(Response.json({}, { status: 503 }));
    await h.ready();
    timers.advance(28_000);
    const listCall = h.calls.find((call) => call.path.includes("/tasks?"));
    assert.equal(listCall.options.signal.aborted, false);
    list.resolve(Response.json(fixtures.body().tasks));
    const x = await h.ready();
    assert.equal(x.tree.props["data-load-state"], "ready");
    assert.equal(h.calls.filter((call) => call.path.includes("/tasks?")).length, 1);
  } finally {
    h.close();
  }
});

test("a genuine overview timeout remains visible until retry verifies the list and available run actions", async () => {
  const timers = controlledTimers(),
    late = Promise.withResolvers();
  const h = harness({
    timers,
    respond: (path) => (path.endsWith("/overview/query") ? late.promise : undefined),
  });
  try {
    await h.ready();
    timers.advance(24_000);
    let x = await h.ready();
    assert.equal(x.m.listError, "request_timeout");
    assert.equal(x.c.capabilityState, "error");
    assert.equal(x.c.enabled, false);
    assert.equal(all(x.tree, (n) => n.props?.children === "noTasks").length, 0);
    assert.equal(h.calls.length, 1);
    const [feedback] = all(x.tree, (n) => n.props?.message === "listTimeout");
    feedback.props.onRetry();
    x = await h.ready();
    late.resolve(Response.json(fixtures.body(undefined, 0)));
    x = await h.ready();
    assert.equal(x.tree.props["data-load-state"], "ready");
    assert.equal(x.c.enabled, true);
    assert.equal(x.m.listError, "");
    assert.equal(x.m.items.length, 2);
    assert.equal(h.calls.filter((c) => c.path.endsWith("/capabilities")).length, 1);
    assert.equal(h.calls.filter((c) => c.path.endsWith("/overview/query")).length, 1);
  } finally {
    h.close();
  }
});

test("one overview 503 recovers task and report reads without a page refresh", async () => {
  const h = harness({
    respond: (path) =>
      path.endsWith("/overview/query") ? Response.json({}, { status: 503 }) : undefined,
  });
  try {
    const { m, c, r, tree } = await h.ready();
    const paths = h.calls.map((call) => call.path);
    assert.equal(paths.filter((path) => path.endsWith("/overview/query")).length, 1);
    for (const path of [
      "/api/v2/tasks?limit=32",
      "/api/v3/task-center/capabilities",
      "/api/v2/persistent-results/vault_A?limit=20",
      "/api/v2/persistent-connections",
    ])
      assert.equal(paths.filter((called) => called === path).length, 1, path);
    assert.equal(m.listReady, true);
    assert.equal(c.capabilityState, "ready");
    assert.equal(r.complete, true);
    assert.equal(r.error, "");
    assert.equal(r.unreadCounts.task_1, 1);
    assert.equal(
      r.providerFor({ kind: "persistent", metadata: fixtures.body().feeds.persistent.items[0] }),
      "muse",
    );
    assert.equal(tree.props["data-load-state"], "ready");
    assert.equal(m.overview.receipt, null);
  } finally {
    h.close();
  }
});

test("opening tasks from another view can recover capabilities from a first overview 503", async () => {
  const h = harness({
    respond: (path) =>
      path.endsWith("/overview/query") ? Response.json({}, { status: 503 }) : undefined,
  });
  try {
    h.active(false);
    await h.ready();
    assert.equal(h.calls.length, 0);
    h.active(true);
    const { c, r, tree } = await h.ready();
    assert.equal(c.capabilityState, "ready");
    assert.equal(r.error, "");
    assert.equal(tree.props["data-load-state"], "ready");
    assert.equal(h.calls.filter((call) => call.path.endsWith("/capabilities")).length, 1);
  } finally {
    h.close();
  }
});

test("explicit metadata refresh during an overview cannot replay old metadata or cancel independent report completion", async () => {
  let release;
  const gate = new Promise((r) => (release = r));
  const h = harness({ respond: (path) => (path.endsWith("/overview/query") ? gate : undefined) });
  try {
    h.render();
    await tick();
    const latest = h.current.m.reloadTasks();
    await latest;
    release(Response.json(fixtures.body()));
    const x = await h.ready();
    assert.equal(x.m.listReady, true);
    assert.equal(x.r.complete, true);
    assert.equal(x.c.capabilityState, "ready");
    assert.equal(h.calls.filter((c) => c.path.endsWith("/overview/query")).length, 1);
    assert.equal(h.calls.filter((c) => c.path.includes("/tasks?")).length, 1);
    assert.equal(x.m.overview.receipt, null, "superseded overview is not reusable cache");
  } finally {
    h.close();
  }
});

test("a fresh Task Center tab keeps names and report counts without new overview reads", async () => {
  const h = harness({ count: 3 });
  try {
    const before = await h.ready();
    assert.equal(Object.keys(before.m.taskNames).length, 3);
    const reads = h.calls.length;
    h.hide(true);
    assert.equal(Object.keys(h.current.m.taskNames).length, 0);
    h.advance(29 * 60 * 1000);
    h.hide(false);
    const after = await h.ready();
    assert.deepEqual(after.m.taskNames, before.m.taskNames);
    assert.deepEqual(after.r.unreadCounts, before.r.unreadCounts);
    assert.equal(h.calls.length, reads);
  } finally {
    h.close();
  }
});

test("visible return waits for its metadata receipt and uses inline packets before requesting names", async () => {
  let block = false,
    release,
    request;
  const gate = new Promise((r) => (release = r));
  const h = harness({
    count: 3,
    respond: (path, o) => {
      if (block && path.endsWith("/overview/query")) {
        request = o.json;
        return gate;
      }
    },
  });
  try {
    await h.ready();
    const start = h.calls.length,
      opens = h.opens.length;
    h.hide(true);
    h.advance(30 * 60 * 1000 + 1);
    block = true;
    h.hide(false);
    const waiting = await h.ready();
    assert.equal(
      h.calls.slice(start).filter((c) => c.path === types.TASK_PACKET_QUERY).length,
      0,
      "retained old list items must wait for the current overview instead of duplicating its inline packets",
    );
    assert.equal(h.opens.length, opens);
    assert.equal(waiting.m.listReady, false);
    assert.notEqual(waiting.tree.props["data-load-state"], "ready");
    release(Response.json(fixtures.body(request, 3)));
    const done = await h.ready();
    assert.equal(h.calls.length - start, 1);
    assert.equal(Object.keys(done.m.taskNames).length, 3);
    assert.equal(h.opens.length - opens, 3);
    assert.equal(done.r.unreadCounts.task_1, 1);
    assert.equal(
      done.r.providerFor({
        kind: "persistent",
        metadata: fixtures.body().feeds.persistent.items[0],
      }),
      "muse",
    );
    assert.equal(done.tree.props["data-load-state"], "ready");
  } finally {
    release(Response.json(fixtures.body(request, 3)));
    h.close();
  }
});

test("visible overview fallback reads only uncovered names through strictly shrinking short pages", async () => {
  for (const inline of ["full", "partial", "null"]) {
    let block = false,
      release,
      request;
    const gate = new Promise((r) => (release = r));
    const h = harness({
      count: 6,
      respond: (path, o) => {
        if (block && path.endsWith("/overview/query")) {
          request = o.json;
          return gate;
        }
        if (path === types.TASK_PACKET_QUERY) {
          const ids = o.json.taskIds,
            body = fixtures.batch(ids.slice(0, 1), fixtures.body(undefined, 6).tasks.items);
          body.remainingTaskIds = ids.slice(1);
          return Response.json(body);
        }
      },
    });
    try {
      await h.ready();
      h.hide(true);
      h.advance(30 * 60 * 1000 + 1);
      block = true;
      const start = h.calls.length;
      h.hide(false);
      await h.ready();
      assert.equal(
        h.calls.slice(start).filter((c) => c.path === types.TASK_PACKET_QUERY).length,
        0,
      );
      const response = fixtures.body(request, 6);
      if (inline === "null") response.packets = null;
      if (inline === "partial") {
        const ids = overview.overviewPacketIds(response.tasks.items, request.knownPacketVersions);
        response.packets = fixtures.batch(ids.slice(0, 1), response.tasks.items);
        response.packets.remainingTaskIds = ids.slice(1);
      }
      release(Response.json(response));
      let done = await h.ready();
      for (let i = 0; i < 8 && Object.keys(done.m.taskNames).length !== 6; i++)
        done = await h.ready();
      const queries = h.calls.slice(start).filter((c) => c.path === types.TASK_PACKET_QUERY);
      const served = new Set(
        inline === "full"
          ? ["task_1", "task_2", "task_3", "task_4"]
          : inline === "partial"
            ? ["task_1"]
            : [],
      );
      assert.equal(
        queries.length,
        6 - served.size,
        "one real suffix query per uncovered short-page item",
      );
      assert.ok(queries.every((c) => c.options.json.taskIds.every((id) => !served.has(id))));
      assert.equal(
        h.calls.slice(start).filter((c) => c.path.endsWith("/overview/query")).length,
        1,
      );
      assert.equal(Object.keys(done.m.taskNames).length, 6);
      assert.equal(done.tree.props["data-load-state"], "ready");
    } finally {
      release(Response.json(fixtures.body(request, 6)));
      h.close();
    }
  }
});

test("a non-503 metadata failure retains the list and waits for an explicit retry", async () => {
  let failed = false;
  const h = harness({
    count: 3,
    respond: (path) =>
      failed && path.endsWith("/overview/query") ? Response.json({}, { status: 500 }) : undefined,
  });
  try {
    await h.ready();
    h.hide(true);
    h.advance(30 * 60 * 1000 + 1);
    failed = true;
    const start = h.calls.length;
    h.hide(false);
    let x = await h.ready();
    assert.equal(x.m.items.length, 3, "keep the real prior task list visible");
    assert.ok(x.m.listError);
    assert.equal(Object.keys(x.m.taskNames).length, 0);
    assert.equal(h.calls.slice(start).filter((c) => c.path === types.TASK_PACKET_QUERY).length, 0);
    assert.equal(x.tree.props["data-load-state"], "error");
    const retry = h.calls.length;
    await x.m.reloadTasks();
    x = await h.ready();
    assert.equal(h.calls.slice(retry).filter((c) => c.path.includes("/tasks?")).length, 1);
    assert.equal(h.calls.slice(retry).filter((c) => c.path.endsWith("/overview/query")).length, 0);
    assert.equal(h.calls.slice(retry).filter((c) => c.path === types.TASK_PACKET_QUERY).length, 1);
    assert.equal(Object.keys(x.m.taskNames).length, 3);
  } finally {
    h.close();
  }
});

test("explicit name retry and overview-disabled task reads retain the original packet route", async () => {
  let fail = true;
  const h = harness({
    open: (p) => {
      if (fail && p.metadata.taskId === "task_2") throw Error("invalid_response");
      return { name: `Name ${p.metadata.taskId}` };
    },
  });
  try {
    let x = await h.ready();
    assert.ok(x.m.nameErrors.task_2);
    const start = h.calls.length;
    fail = false;
    x.m.retryTaskName("task_2");
    x = await h.ready();
    assert.equal(h.calls.length - start, 1);
    assert.equal(h.calls.at(-1).path, types.TASK_PACKET_QUERY);
    assert.deepEqual(Array.from(h.calls.at(-1).options.json.taskIds), ["task_2"]);
    assert.equal(x.m.taskNames.task_2, "Name task_2");
  } finally {
    h.close();
  }
  const legacy = harness({ overviewEnabled: false, count: 3 });
  try {
    const x = await legacy.ready();
    assert.equal(legacy.calls.filter((c) => c.path.endsWith("/overview/query")).length, 0);
    assert.equal(legacy.calls.filter((c) => c.path.includes("/tasks?")).length, 1);
    assert.equal(legacy.calls.filter((c) => c.path === types.TASK_PACKET_QUERY).length, 1);
    assert.equal(Object.keys(x.m.taskNames).length, 3);
  } finally {
    legacy.close();
  }
});

test("a superseded name receipt cannot publish late Worker output or exceed the original two workers", async () => {
  const releases = [];
  let active = 0,
    maximum = 0;
  const h = harness({
    count: 6,
    open: (p) =>
      new Promise((r) => {
        active++;
        maximum = Math.max(maximum, active);
        releases.push((name = `Name ${p.metadata.taskId}`) => {
          active--;
          r({ name });
        });
      }),
  });
  try {
    let x = await h.ready();
    assert.equal(releases.length, 2);
    await x.m.reloadTasks();
    await h.ready();
    releases.splice(0).forEach((r) => r("SUPERSEDED_NAME"));
    x = await h.ready();
    assert.equal(Object.keys(x.m.taskNames).length, 0);
    assert.notEqual(x.tree.props["data-load-state"], "ready");
    for (let i = 0; i < 8 && Object.keys(x.m.taskNames).length !== 6; i++) {
      releases.splice(0).forEach((r) => r());
      x = await h.ready();
    }
    assert.equal(Object.keys(x.m.taskNames).length, 6);
    assert.ok(Object.values(x.m.taskNames).every((n) => n !== "SUPERSEDED_NAME"));
    assert.equal(maximum, 2);
  } finally {
    h.active(false);
    releases.splice(0).forEach((r) => r());
    h.close();
  }
});

test("late fallback packet replies cannot restore names after demand or private scope changes", async () => {
  for (const boundary of ["inactive", "hidden", "owner", "vault", "lock"]) {
    let release,
      count = 0;
    const gate = new Promise((r) => (release = r));
    const h = harness({
      respond: (path) => {
        if (path.endsWith("/overview/query")) {
          if (++count > 1) return new Promise(() => {});
          const b = fixtures.body();
          b.packets = null;
          return Response.json(b);
        }
        if (path === types.TASK_PACKET_QUERY) return gate;
      },
    });
    try {
      await h.ready();
      assert.equal(h.calls.filter((c) => c.path === types.TASK_PACKET_QUERY).length, 1);
      if (boundary === "inactive") h.active(false);
      else if (boundary === "hidden") h.hide(true);
      else if (boundary === "owner") h.owner("owner_B");
      else {
        if (boundary === "vault") h.workspace.vaultGeneration++;
        else h.workspace.phase = "locked";
        h.render();
      }
      release(Response.json(fixtures.batch(["task_1", "task_2"], fixtures.body().tasks.items)));
      const x = await h.ready();
      assert.equal(h.opens.length, 0, boundary);
      assert.equal(Object.keys(x.m.taskNames).length, 0, boundary);
      assert.notEqual(x.tree.props["data-load-state"], "ready", boundary);
    } finally {
      release(Response.json(fixtures.batch(["task_1", "task_2"], fixtures.body().tasks.items)));
      h.close();
    }
  }
});

test("an old packet failure cannot mark names unavailable under a newer metadata receipt", async () => {
  let release,
    packetReads = 0;
  const gate = new Promise((r) => (release = r));
  const h = harness({
    respond: (path, o) => {
      if (path.endsWith("/overview/query")) {
        const b = fixtures.body(o.json);
        b.packets = null;
        return Response.json(b);
      }
      if (path === types.TASK_PACKET_QUERY && ++packetReads === 1) return gate;
    },
  });
  try {
    let x = await h.ready();
    assert.equal(packetReads, 1);
    await x.m.reloadTasks();
    await h.ready();
    release(Response.json({}, { status: 503 }));
    x = await h.ready();
    assert.equal(Object.keys(x.m.nameErrors).length, 0);
    assert.equal(Object.keys(x.m.taskNames).length, 2);
    assert.equal(packetReads, 2);
    assert.equal(x.m.listReady, true);
  } finally {
    release(Response.json({}, { status: 503 }));
    h.close();
  }
});

test("shared unlock restoration after an authenticated locked mount verifies current inline task names", async () => {
  for (const phase of ["checking", "locked"]) {
    const h = harness({ count: 3 });
    try {
      h.workspace.phase = phase;
      h.workspace.vault = null;
      const locked = await h.ready();
      assert.equal(locked.m.listReady, false);
      assert.equal(locked.m.listError, "");
      assert.equal(h.opens.length, 0);
      await locked.m.reload();
      await locked.m.reloadTasks();
      await locked.m.reloadCatalogue();
      assert.equal(h.calls.length, 0, "a locked page has no task or catalogue request");
      assert.equal(h.render().m.listError, "");
      h.workspace.phase = "unlocked";
      h.workspace.vault = { vaultId: "vault_A", version: 1 };
      const restored = await h.ready();
      assert.equal(h.calls.length, 1);
      assert.ok(h.calls[0].path.endsWith("/overview/query"));
      assert.equal(restored.m.items.length, 3);
      assert.equal(restored.m.listReady, true);
      assert.equal(h.opens.length, 3, "names still require each original Worker proof");
      assert.equal(Object.keys(restored.m.taskNames).length, 3);
      assert.equal(Object.keys(restored.m.nameErrors).length, 0);
      assert.equal(restored.tree.props["data-load-state"], "ready");
      assert.equal(restored.tree.props["aria-busy"], false);
    } finally {
      h.close();
    }
  }
});

test("an obsolete overview cannot satisfy a new unlock generation or publish while locked", async () => {
  let release,
    attempts = 0;
  const gate = new Promise((resolve) => (release = resolve));
  const h = harness({
    count: 3,
    respond: (path) => (path.endsWith("/overview/query") && ++attempts === 1 ? gate : undefined),
  });
  try {
    h.render();
    await tick();
    assert.equal(h.calls.length, 1);
    h.workspace.phase = "locked";
    h.workspace.vault = null;
    let current = await h.ready();
    release(Response.json(fixtures.body(undefined, 3)));
    current = await h.ready();
    assert.equal(current.m.listReady, false);
    assert.equal(Object.keys(current.m.taskNames).length, 0);
    assert.equal(h.opens.length, 0);
    h.workspace.phase = "unlocked";
    h.workspace.vault = { vaultId: "vault_A", version: 1 };
    h.workspace.vaultGeneration++;
    current = await h.ready();
    assert.equal(h.calls.length, 2);
    assert.equal(current.m.listReady, true);
    assert.equal(h.opens.length, 3);
    assert.equal(Object.keys(current.m.taskNames).length, 3);
    assert.equal(current.tree.props["data-load-state"], "ready");
  } finally {
    release(Response.json(fixtures.body(undefined, 3)));
    h.close();
  }
});

test("late Worker success or failure cannot cross an Owner or unlock generation change", async () => {
  for (const boundary of ["owner", "generation", "lock"]) {
    for (const failure of [false, true]) {
      let release,
        attempt = 0;
      const gate = new Promise((resolve, reject) => {
        release = () =>
          failure ? reject(Error("invalid_response")) : resolve({ name: "Obsolete name" });
      });
      const h = harness({
        count: 1,
        open: () => (++attempt === 1 ? gate : { name: "Current name" }),
      });
      try {
        const waiting = await h.ready();
        assert.equal(h.opens.length, 1);
        assert.notEqual(waiting.tree.props["data-load-state"], "ready");
        if (boundary === "owner") h.owner("owner_B");
        else if (boundary === "generation") h.workspace.vaultGeneration++;
        else {
          h.workspace.phase = "locked";
          h.workspace.vault = null;
        }
        let current = await h.ready();
        assert.equal(Object.values(current.m.taskNames).includes("Obsolete name"), false);
        release();
        current = await h.ready();
        if (boundary === "lock") {
          assert.equal(current.m.listReady, false);
          assert.equal(Object.keys(current.m.taskNames).length, 0);
          assert.equal(Object.keys(current.m.nameErrors).length, 0);
          h.workspace.phase = "unlocked";
          h.workspace.vault = { vaultId: "vault_A", version: 1 };
          h.workspace.vaultGeneration++;
          current = await h.ready();
        }
        assert.equal(current.m.listReady, true);
        assert.equal(current.m.taskNames.task_1, "Current name");
        assert.equal(Object.keys(current.m.nameErrors).length, 0);
        assert.equal(Object.values(current.m.taskNames).includes("Obsolete name"), false);
        assert.equal(h.calls.filter((call) => call.path.endsWith("/overview/query")).length, 2);
      } finally {
        release();
        h.close();
      }
    }
  }
});

function currentVaultFixture() {
  return {
    contractVersion: types.TASK_CONTRACT,
    vault: { vaultId: "vault_A", version: 1 },
    sources: [],
  };
}
function detailFixture(id, packet, patch = {}) {
  return {
    contractVersion: types.TASK_CONTRACT,
    profile: "folioview.owner-task-detail.v1",
    state: {
      contractVersion: types.TASK_CONTRACT,
      profile: "folioview.task-center.v1",
      taskId: id,
      taskVersion: 1,
      executionEpoch: 1,
      rules: null,
      assignments: [],
    },
    legacy: null,
    attribution: null,
    packet,
    taskMetadata: fixtures.metadata(Number(id.split("_")[1])),
    vaultResponse: { status: "ready", data: currentVaultFixture() },
    ...patch,
  };
}
const syntheticForm = () =>
  compile("../lib/task-forms.ts", { "./task-types": types }).defaultTask("custom");
test("one selected-task query and manual history start together; verified vault unlocks the body and executor state and a fresh revisit sends nothing", async () => {
  let releaseVault,
    receivedVault,
    verifications = 0;
  const h = harness({
    open: () => ({ ...syntheticForm(), name: "Synthetic", goal: "Research" }),
    readDetail: require("./task-overview-helpers.cjs").detail.readTaskDetail,
    respond: (path, opts) => {
      if (path.endsWith("/detail/query"))
        return Response.json(
          detailFixture(
            "task_1",
            opts.json.includePacket
              ? { status: "ready", data: fixtures.packet(fixtures.metadata(1)) }
              : null,
          ),
        );
      if (path.endsWith("/manual")) return Response.json({ items: [] });
    },
  });
  try {
    await h.ready();
    h.advance(30_001);
    h.workspace.loadTaskCenterPending = async () => null;
    h.workspace.verifyTaskCenterState = async (s) => {
      verifications++;
      return s;
    };
    h.workspace.refreshVault = async (signal, forWrite, response) => {
      assert.equal(signal.aborted, false);
      assert.equal(forWrite, false);
      receivedVault = await (await response()).json();
      return new Promise((resolve) => {
        releaseVault = resolve;
      });
    };
    const before = h.calls.length;
    const opening = h.current.m.openTask("task_1");
    let result = await h.ready();
    assert.equal(typeof releaseVault, "function");
    const query = h.calls.slice(before).filter((c) => c.path.endsWith("/detail/query"));
    assert.equal(query.length, 1);
    assert.equal(query[0].options.json.includePacket, true);
    assert.equal(query[0].options.json.includeVault, true);
    assert.deepEqual(receivedVault, currentVaultFixture());
    assert.equal(verifications, 0);
    assert.equal(result.m.selected, null);
    assert.deepEqual(
      h.calls.slice(before).map((c) => c.path.split("/").at(-1)),
      ["query", "manual"],
    );
    releaseVault(h.workspace.vault);
    await opening;
    result = await h.ready();
    assert.equal(result.m.selected.taskId, "task_1");
    assert.equal(result.c.executors.status, "ready");
    assert.equal(verifications, 1);
    const paths = h.calls.slice(before).map((c) => c.path);
    assert.equal(
      paths.some(
        (p) =>
          p.endsWith("/tasks/task_1") ||
          p.endsWith("/authority") ||
          p.endsWith("/persistent-connections"),
      ),
      false,
    );
    const n = h.calls.length;
    await result.m.openTask("task_1");
    await h.ready();
    assert.equal(h.calls.length, n);
  } finally {
    h.close();
  }
});
test("an unavailable bundled packet alone retries the original head; a denied entire selection never falls back", async () => {
  for (const denied of [false, true]) {
    const h = harness({
      readDetail: require("./task-overview-helpers.cjs").detail.readTaskDetail,
      open: () => ({ ...syntheticForm(), name: "Synthetic", goal: "Research" }),
      respond: (p) => {
        if (p.endsWith("/detail/query"))
          return denied
            ? Response.json({}, { status: 403 })
            : Response.json(detailFixture("task_1", { status: "unavailable" }));
        if (p === "/api/v2/tasks/task_1")
          return Response.json(fixtures.packet(fixtures.metadata(1)));
        if (p.endsWith("/manual")) return Response.json({ items: [] });
      },
    });
    try {
      await h.ready();
      h.advance(30_001);
      h.workspace.loadTaskCenterPending = async () => null;
      h.workspace.verifyTaskCenterState = async (s) => s;
      h.workspace.refreshVault = async () => h.workspace.vault;
      const opening = h.current.m.openTask("task_1");
      await h.ready();
      await opening;
      const r = await h.ready();
      assert.equal(r.m.selected?.taskId, denied ? undefined : "task_1");
      assert.equal(h.calls.filter((c) => c.path === "/api/v2/tasks/task_1").length, denied ? 0 : 1);
      assert.equal(
        h.calls.filter((c) => c.path === "/api/v3/task-center/vault_A/tasks/task_1").length,
        0,
      );
    } finally {
      h.close();
    }
  }
});

test("a new selection discards a late body, state and early manual history even if transport ignores abort", async () => {
  let releaseA, releaseHistory;
  const h = harness({
    readDetail: require("./task-overview-helpers.cjs").detail.readTaskDetail,
    open: () => ({ ...syntheticForm(), name: "Synthetic", goal: "Research" }),
    respond: (path, opts) => {
      if (path.endsWith("/detail/query")) {
        const id = path.includes("/task_1/") ? "task_1" : "task_2";
        const response = () =>
          Response.json(
            detailFixture(
              id,
              opts.json.includePacket
                ? {
                    status: "ready",
                    data: fixtures.packet(fixtures.metadata(id === "task_1" ? 1 : 2)),
                  }
                : null,
            ),
          );
        if (id === "task_1")
          return new Promise((resolve) => {
            releaseA = () => resolve(response());
          });
        return response();
      }
      if (path.endsWith("/task_1/manual"))
        return new Promise((resolve) => {
          releaseHistory = () =>
            resolve(Response.json({ items: [{ aggregate: { hasActiveExecutors: true } }] }));
        });
      if (path.endsWith("/manual")) return Response.json({ items: [] });
    },
  });
  try {
    await h.ready();
    h.advance(30_001);
    h.workspace.loadTaskCenterPending = async () => null;
    h.workspace.verifyTaskCenterState = async (s) => s;
    h.workspace.refreshVault = async () => h.workspace.vault;
    const first = h.current.m.openTask("task_1");
    await h.ready();
    assert.equal(
      typeof releaseHistory,
      "function",
      "queue the required manual read after the combined request starts, before it finishes",
    );
    assert.equal(h.calls.filter((c) => c.path.endsWith("/task_1/manual")).length, 1);
    assert.ok(
      h.calls.findIndex((c) => c.path.endsWith("/task_1/detail/query")) <
        h.calls.findIndex((c) => c.path.endsWith("/task_1/manual")),
    );
    const second = h.current.m.openTask("task_2");
    await h.ready();
    await second;
    releaseHistory();
    releaseA();
    await first;
    const r = await h.ready();
    assert.equal(r.m.selected.taskId, "task_2");
    assert.equal(r.c.selectedRecord.taskId, "task_2");
    assert.equal(r.c.manual.task_1, undefined);
    assert.equal(r.c.runState, "ready");
    assert.equal(h.calls.filter((c) => c.path.endsWith("/task_2/manual")).length, 1);
    assert.equal(h.calls.filter((c) => c.path.endsWith("/detail/query")).length, 2);
  } finally {
    h.close();
  }
});

test("a fresh inline packet cannot open until the selected vault response is verified", async () => {
  let finish;
  const h = harness({
    readDetail: require("./task-overview-helpers.cjs").detail.readTaskDetail,
    open: () => ({ ...syntheticForm(), name: "Synthetic", goal: "Research" }),
    respond: (path, opts) => {
      if (path.endsWith("/detail/query")) {
        assert.equal(opts.json.includePacket, false);
        return new Promise((resolve) => {
          finish = () => resolve(Response.json({}, { status: 503 }));
        });
      }
      if (path.endsWith("/manual")) return Response.json({ items: [] });
    },
  });
  try {
    await h.ready();
    h.workspace.loadTaskCenterPending = async () => null;
    h.workspace.verifyTaskCenterState = async (s) => s;
    h.workspace.refreshVault = async () => h.workspace.vault;
    const opened = h.current.m.openTask("task_1");
    let result = await h.ready();
    assert.equal(typeof finish, "function");
    assert.equal(result.m.selected, null);
    assert.equal(result.c.executors.status, "loading");
    finish();
    await opened;
    result = await h.ready();
    assert.equal(result.m.selected, null);
    assert.ok(result.m.error);
    assert.equal(h.calls.filter((c) => c.path === "/api/v2/tasks/task_1").length, 0);
    assert.equal(h.calls.filter((c) => c.path.endsWith("/tasks/task_1/manual")).length, 1);
  } finally {
    h.close();
  }
});

test("opening a task whose historical run is already in the overview keeps the feed and unread count", async () => {
  const h = harness({
    open: () => ({ ...syntheticForm(), name: "Synthetic", goal: "Research" }),
    respond: (path) => {
      if (path.endsWith("/tasks/task_1/manual"))
        return Response.json({
          items: [
            {
              snapshot: { executors: [{ resultId: "result_A" }] },
              aggregate: { hasActiveExecutors: false },
            },
          ],
        });
      if (path.endsWith("/tasks/task_1")) return Response.json(detailFixture("task_1", null).state);
    },
  });
  try {
    let m = await h.ready();
    h.workspace.verifyTaskCenterState = async (s) => s;
    h.workspace.loadTaskCenterPending = async () => null;
    h.workspace.refreshVault = async () => h.workspace.vault;
    const receipt = m.m.overview.receipt;
    assert.equal(m.r.unreadCounts.task_1, 1);
    await m.m.openTask("task_1");
    m = await h.ready();
    assert.equal(m.c.manual.task_1[0].snapshot.executors[0].resultId, "result_A");
    assert.equal(m.m.overview.receipt, receipt);
    assert.equal(m.r.unreadCounts.task_1, 1);
    assert.equal(h.calls.filter((c) => c.path.includes("?limit=")).length, 0);
  } finally {
    h.close();
  }
});

function selectedReadFixture(id, options, patch = {}) {
  const meta = fixtures.metadata(Number(id.split("_")[1]));
  const wire = detailFixture(
    id,
    options.includePacket ? { status: "ready", data: fixtures.packet(meta) } : null,
    patch,
  );
  if (!options.includeVault) {
    delete wire.taskMetadata;
    delete wire.vaultResponse;
  }
  return Response.json(wire);
}

function selectionHarness(patch = () => ({})) {
  const h = harness({
    readDetail: require("./task-overview-helpers.cjs").detail.readTaskDetail,
    open: () => ({ ...syntheticForm(), name: "Synthetic", goal: "Research" }),
    respond: (path, options) => {
      if (path.endsWith("/detail/query")) {
        const id = path.split("/").at(-3);
        return selectedReadFixture(id, options.json, patch(id));
      }
      if (path.endsWith("/manual")) return Response.json({ items: [] });
      if (path === "/api/v2/vaults/current") return Response.json(currentVaultFixture());
      if (path === "/api/v2/tasks/task_1")
        return Response.json(fixtures.packet(fixtures.metadata(1)));
    },
  });
  h.workspace.loadTaskCenterPending = async () => null;
  h.workspace.verifyTaskCenterState = async (s) => s;
  h.workspace.refreshVault = async (signal, forWrite, bundled) => {
    assert.equal(forWrite, false);
    const response = bundled
      ? await bundled()
      : await h.requestPrivate("agent-hub", "/api/v2/vaults/current", h.workspace.owner, {
          signal,
        });
    const dto = await response.json();
    assert.deepEqual(dto, currentVaultFixture());
    return h.workspace.vault;
  };
  return h;
}

test("an unavailable vault retries only its normal GET, without repeating the detail, body or controls", async () => {
  const h = selectionHarness(() => ({ vaultResponse: { status: "unavailable" } }));
  try {
    await h.ready();
    h.advance(30_001);
    const before = h.calls.length;
    const opening = h.current.m.openTask("task_1");
    await h.ready();
    await opening;
    const result = await h.ready();
    assert.equal(result.m.selected.taskId, "task_1");
    assert.equal(result.c.runState, "ready");
    const paths = h.calls.slice(before).map((c) => c.path);
    assert.equal(paths.length, 3);
    assert.equal(paths.filter((p) => p.endsWith("/detail/query")).length, 1);
    assert.equal(paths.filter((p) => p.endsWith("/manual")).length, 1);
    assert.equal(paths.filter((p) => p === "/api/v2/vaults/current").length, 1);
  } finally {
    h.close();
  }
});

test("an inline carrier is renewed only by a new complete head and verified bundled vault, dated at network receipt", async () => {
  const h = selectionHarness();
  try {
    await h.ready();
    h.advance(29_000);
    let release;
    const refresh = h.workspace.refreshVault;
    let vaultReads = 0;
    h.workspace.refreshVault = async (...args) => {
      vaultReads++;
      const verified = await refresh(...args);
      if (vaultReads === 1)
        await new Promise((resolve) => {
          release = resolve;
        });
      return verified;
    };
    const before = h.calls.length;
    const select = async () => {
      const opening = h.current.m.openTask("task_1");
      await h.ready();
      await opening;
      const result = await h.ready();
      assert.equal(result.m.selected?.taskId, "task_1");
      assert.equal(result.c.runState, "ready");
    };
    const first = h.current.m.openTask("task_1");
    await h.ready();
    assert.equal(typeof release, "function");
    h.advance(7_000);
    release();
    await first;
    assert.equal((await h.ready()).m.selected.taskId, "task_1");
    // Overview evidence has now expired, while the new network receipt is only seven seconds old.
    h.advance(20_000);
    await select();
    assert.equal(vaultReads, 1);
    // Neither decrypt completion nor the intervening control-only read extends the new receipt.
    h.advance(3_001);
    await select();
    assert.equal(vaultReads, 2);
    const queries = h.calls.slice(before).filter((c) => c.path.endsWith("/detail/query"));
    assert.deepEqual(
      queries.map((c) => [!!c.options.json.includeVault, c.options.json.includePacket]),
      [
        [true, false],
        [false, false],
        [true, false],
      ],
    );
    assert.equal(
      h.calls
        .slice(before)
        .filter((c) => c.path === "/api/v2/tasks/task_1" || c.path === "/api/v2/vaults/current")
        .length,
      0,
    );
  } finally {
    h.close();
  }
});

test("expired local ciphertext needs a fresh head GET when the vault was read separately", async () => {
  let unavailable = false;
  const h = selectionHarness(() =>
    unavailable ? { vaultResponse: { status: "unavailable" } } : {},
  );
  try {
    await h.ready();
    const first = h.current.m.openTask("task_1");
    await h.ready();
    await first;
    await h.ready();
    unavailable = true;
    h.advance(30_001);
    const before = h.calls.length;
    const second = h.current.m.openTask("task_1");
    await h.ready();
    await second;
    assert.equal((await h.ready()).m.selected.taskId, "task_1");
    const paths = h.calls.slice(before).map((c) => c.path);
    assert.equal(paths.filter((p) => p === "/api/v2/vaults/current").length, 1);
    assert.equal(paths.filter((p) => p === "/api/v2/tasks/task_1").length, 1);
  } finally {
    h.close();
  }
});

test("invalid scope, metadata, or vault verification hides the selected body and controls and never falls back", async () => {
  for (const fault of ["head", "vault-scope", "missing-data", "revoked", "vault-version", "root"]) {
    let bad = true;
    const h = selectionHarness(() => {
      if (!bad) return {};
      if (fault === "head") return { taskMetadata: { ...fixtures.metadata(1), objectRevision: 7 } };
      if (fault === "vault-scope")
        return {
          vaultResponse: {
            status: "ready",
            data: { ...currentVaultFixture(), vault: { vaultId: "vault_B" } },
          },
        };
      if (fault === "missing-data") return { vaultResponse: { status: "ready" } };
      return {};
    });
    try {
      await h.ready();
      const before = h.calls.length;
      const verify = h.workspace.refreshVault;
      h.workspace.refreshVault = async (...args) => {
        const v = await verify(...args);
        if (!bad) return v;
        if (fault === "revoked") throw new Error("revoked");
        if (fault === "vault-version") return { ...v, version: 2 };
        if (fault === "root") return { ...v, rootKeyId: "root_B" };
        return v;
      };
      const namesOpens = h.opens.length;
      const opening = h.current.m.openTask("task_1");
      await h.ready();
      await opening;
      let result = await h.ready();
      assert.equal(result.m.selected, null, fault);
      assert.ok(result.m.error, fault);
      assert.equal(result.c.selectedRecord?.taskId, undefined, fault);
      assert.equal(h.opens.length, namesOpens, fault);
      assert.equal(
        h.calls
          .slice(before)
          .some((c) => c.path === "/api/v2/vaults/current" || c.path === "/api/v2/tasks/task_1"),
        false,
        fault,
      );
      bad = false;
      const next = result.m.openTask("task_1");
      await h.ready();
      await next;
      result = await h.ready();
      assert.equal(result.m.selected?.taskId, "task_1", fault);
      assert.equal(result.c.runState, "ready", fault);
      assert.equal(
        h.calls.slice(before).filter((c) => c.options.json?.includeVault).length,
        2,
        fault,
      );
    } finally {
      h.close();
    }
  }
});

test("a late vault verification cannot publish the former selection or its available actions", async () => {
  const h = selectionHarness();
  try {
    await h.ready();
    const verifier = h.workspace.refreshVault;
    let release,
      count = 0;
    h.workspace.refreshVault = async (...args) => {
      const vault = await verifier(...args);
      if (++count === 1)
        await new Promise((resolve) => {
          release = resolve;
        });
      return vault;
    };
    const a = h.current.m.openTask("task_1");
    await h.ready();
    assert.equal(typeof release, "function");
    const b = h.current.m.openTask("task_2");
    await h.ready();
    await b;
    let result = await h.ready();
    assert.equal(result.m.selected.taskId, "task_2");
    release();
    await a;
    result = await h.ready();
    assert.equal(result.m.selected.taskId, "task_2");
    assert.equal(result.c.selectedRecord.taskId, "task_2");
    assert.equal(result.c.runState, "ready");
  } finally {
    h.close();
  }
});

test("a direct link opens an unlisted task without waiting for the overview and shares controls with history", async () => {
  for (const pendingOverview of [true, false]) {
    let finishOverview, finishControls;
    const list = new Promise((resolve) => {
      finishOverview = resolve;
    });
    const h = harness({
      readDetail: require("./task-overview-helpers.cjs").detail.readTaskDetail,
      open: () => ({ ...syntheticForm(), name: "Linked task", goal: "Research" }),
      respond: (path, options) => {
        if (path.endsWith("/overview/query")) return list;
        if (path === "/api/v2/tasks/task_9")
          return Response.json(fixtures.packet(fixtures.metadata(9)));
        if (path === "/api/v3/task-center/vault_A/tasks/task_9") {
          return new Promise((resolve) => {
            finishControls = () => resolve(Response.json(detailFixture("task_9", null).state));
          });
        }
        if (path.endsWith("/task_9/manual")) return Response.json({ items: [] });
      },
    });
    try {
      if (!pendingOverview) finishOverview(Response.json({}, { status: 503 }));
      await h.ready();
      h.workspace.loadTaskCenterPending = async () => null;
      h.workspace.verifyTaskCenterState = async (s) => s;
      let vaultReads = 0;
      h.workspace.refreshVault = async (signal, forWrite, bundled, reuseStartup) => {
        assert.equal(forWrite, false);
        assert.equal(reuseStartup, true);
        vaultReads++;
        return h.workspace.vault;
      };
      await h.current.m.openLinkedTask("task_9");
      let current = await h.ready();
      assert.equal(current.m.selected?.taskId, "task_9");
      assert.equal(vaultReads, 1);
      assert.equal(typeof finishControls, "function");
      assert.equal(current.c.runState, "loading");
      assert.deepEqual(
        h.calls.filter((c) => c.path.includes("task_9")).map((c) => c.path.split("/").at(-1)),
        ["task_9", "task_9", "manual"],
      );
      finishControls();
      current = await h.ready();
      assert.equal(current.c.runState, "ready");
      assert.equal(h.calls.filter((c) => c.path.includes("task_9")).length, 3);
    } finally {
      finishOverview(Response.json(fixtures.body()));
      h.close();
    }
  }
});

test("independent User display verification overlaps the selected Hub read and fails closed on a changed root", async () => {
  for (const changed of [false, true]) {
    let finishDetail,
      finishVault,
      vaultReads = 0;
    const h = harness({
      userVault: true,
      readDetail: require("./task-overview-helpers.cjs").detail.readTaskDetail,
      open: () => ({ ...syntheticForm(), name: "Synthetic", goal: "Research" }),
      respond: (path, options) => {
        if (path.endsWith("/detail/query"))
          return new Promise((resolve) => {
            finishDetail = () => resolve(selectedReadFixture("task_1", options.json));
          });
        if (path.endsWith("/manual")) return Response.json({ items: [] });
      },
    });
    try {
      await h.ready();
      h.workspace.loadTaskCenterPending = async () => null;
      h.workspace.verifyTaskCenterState = async (s) => s;
      h.workspace.refreshVault = async (signal, forWrite) => {
        assert.ok(!forWrite);
        vaultReads++;
        return new Promise((resolve) => {
          finishVault = () =>
            resolve(
              changed ? { ...h.workspace.vault, rootKeyId: "another_root" } : h.workspace.vault,
            );
        });
      };
      const opening = h.current.m.openTask("task_1");
      await h.ready();
      assert.equal(typeof finishVault, "function");
      assert.equal(typeof finishDetail, "function");
      finishDetail();
      assert.equal((await h.ready()).m.selected, null);
      finishVault();
      await opening;
      const current = await h.ready();
      assert.equal(vaultReads, 1);
      assert.equal(current.m.selected?.taskId, changed ? undefined : "task_1");
      assert.equal(current.m.error, changed ? "version_conflict" : "");
    } finally {
      h.close();
    }
  }
});

test("a linked task reuses a just-arrived overview packet before list render, but an expired packet requires the original read", async () => {
  for (const expired of [false, true]) {
    let finishOverview;
    const list = new Promise((resolve) => {
      finishOverview = resolve;
    });
    const h = harness({
      readDetail: require("./task-overview-helpers.cjs").detail.readTaskDetail,
      open: () => ({ ...syntheticForm(), name: "Linked task", goal: "Research" }),
      respond: (path) => {
        if (path.endsWith("/overview/query")) return list;
        if (path === "/api/v2/tasks/task_1")
          return Response.json(fixtures.packet(fixtures.metadata(1)));
        if (path === "/api/v3/task-center/vault_A/tasks/task_1")
          return Response.json(detailFixture("task_1", null).state);
        if (path.endsWith("/task_1/manual")) return Response.json({ items: [] });
      },
    });
    try {
      await h.ready();
      h.workspace.loadTaskCenterPending = async () => null;
      h.workspace.verifyTaskCenterState = async (s) => s;
      h.workspace.refreshVault = async () => h.workspace.vault;
      const reading = h.current.m.overview.acquire();
      finishOverview(Response.json(fixtures.body()));
      await reading;
      assert.equal(h.current.m.items.length, 0);
      if (expired) h.advance(30_000);
      await h.current.m.openLinkedTask("task_1");
      const result = await h.ready();
      assert.equal(result.m.selected?.taskId, "task_1");
      assert.equal(
        h.calls.filter((c) => c.path === "/api/v2/tasks/task_1").length,
        expired ? 1 : 0,
      );
    } finally {
      h.close();
    }
  }
});
