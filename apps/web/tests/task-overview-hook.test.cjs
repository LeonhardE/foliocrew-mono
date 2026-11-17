const test = require("node:test"),
  assert = require("node:assert/strict");
const { compile } = require("./resource-library-helpers.cjs"),
  { hooks, jsx } = require("./resource-ui-harness.cjs");
const { types, overview, reader, inbox, providers } = require("./task-overview-helpers.cjs"),
  fixtures = require("./task-overview-fixtures.cjs");
const tick = () => new Promise((r) => setImmediate(r));
function harness({ count = 2, respond, open, overviewEnabled = true } = {}) {
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
      requestPrivate,
    }),
  };
  const window = {
    location: { hash: "", pathname: "/tasks", search: "" },
    history: { replaceState() {} },
    setTimeout,
    clearTimeout,
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
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    crypto: require("node:crypto").webcrypto,
  };
  const localOverview = compile(
    "../lib/task-overview.ts",
    {
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
      });
      const c = center.useTaskCenter(workspace, active, m.selected, m.overview);
      const r = results.useTaskResults(workspace, undefined, m, active, "", c, m.overview);
      const tree = view.TaskCenterView({ workspace, model: m, center: c, resultState: r, active });
      return (current = { m, c, r, tree });
    });
  return {
    workspace,
    calls,
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
test("explicit list refresh remains one request and report refresh four requests", async () => {
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
    assert.equal(h.calls.length - start, 4);
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
    h.advance(30001);
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
      h.advance(30001);
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

test("failed metadata refresh retains the list without speculative name backfill and explicit list retry stays legacy", async () => {
  let failed = false;
  const h = harness({
    count: 3,
    respond: (path) =>
      failed && path.endsWith("/overview/query") ? Response.json({}, { status: 503 }) : undefined,
  });
  try {
    await h.ready();
    h.hide(true);
    h.advance(30001);
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
      assert.equal(h.opens.length, 0);
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
