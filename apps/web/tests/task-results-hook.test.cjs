const test = require("node:test"),
  assert = require("node:assert/strict");
const { compile } = require("./resource-library-helpers.cjs"),
  inbox = compile("../lib/inbox-types.ts"),
  cache = compile("../lib/workspace-cache.ts"),
  reader = compile("../lib/task-result-reader.ts", { "./inbox-types": inbox }),
  links = compile("../lib/inbox-link.ts", {}, { window: { location: { hash: "" } } });
const C = reader.RESULT_CONTRACT,
  tick = () => new Promise((r) => setTimeout(r, 3));
const meta = () => ({
  resultId: "presult_A",
  taskId: "task_A",
  runId: "run_A",
  connectionId: "connection_A",
  receivedAt: 1000,
  stateVersion: 0,
  read: false,
  starred: false,
  archived: false,
});
function harness({ transport, center, timers, clock = Date, resultsVisible = true } = {}) {
  let observed = "";
  let owner = "owner_A",
    index = 0,
    dirty = false,
    active = true,
    visible = true,
    metadata = meta();
  const cells = [],
    effects = [],
    calls = [],
    events = new Map(),
    docEvents = new Map();
  let signs = 0,
    decrypts = 0,
    hash = "";
  const changed = (a, b) => !a || b.some((v, i) => v !== a[i]);
  const react = {
    useRef(v) {
      const n = index++;
      return (cells[n] ??= { current: v });
    },
    useState(v) {
      const n = index++;
      cells[n] ??= { value: typeof v === "function" ? v() : v };
      return [
        cells[n].value,
        (next) => {
          const v = typeof next === "function" ? next(cells[n].value) : next;
          dirty ||= !Object.is(v, cells[n].value);
          cells[n].value = v;
        },
      ];
    },
    useCallback(v, deps) {
      const n = index++;
      if (!cells[n] || changed(cells[n].deps, deps)) cells[n] = { value: v, deps };
      return cells[n].value;
    },
    useEffect(f, deps) {
      const n = index++;
      if (!cells[n] || changed(cells[n].deps, deps)) effects.push({ n, f, deps });
    },
  };
  const content = {
    title: "PRIVATE_REPORT",
    summary: "PRIVATE_SUMMARY",
    sections: [],
    limitations: [],
  };
  const workspace = {
    owner,
    phase: "unlocked",
    vaultGeneration: 1,
    canWriteState: true,
    vault: { vaultId: "vault_A", rootKeyId: "root_A", registryHistory: [] },
    openPersistentResult: async () => {
      decrypts++;
      return content;
    },
    signPersistentResultState: async ({ metadata, changes }) => {
      signs++;
      return {
        operationId: "original_state_operation_0001",
        authorKeyId: "author_A",
        command: { metadata, changes },
      };
    },
  };
  const model = {
    selected: { taskId: "task_A", taskVersion: 1 },
    busy: false,
    dirty: false,
    pending: null,
    async openTask(task) {
      model.selected = { taskId: task, taskVersion: 1 };
    },
    async reloadTasks() {},
  };
  const requestPrivate = async (_s, path, _o, o) => {
    calls.push({ path, options: o });
    const v = await transport?.(path, o, metadata);
    if (v !== undefined) return v;
    if (path === "/api/v2/persistent-connections")
      return Response.json({
        contractVersion: C,
        profile: "folioview.persistent-account.v1",
        connections: [
          {
            connectionId: "connection_A",
            clientId: "client_A",
            vaultId: "vault_A",
            provider: "muse",
            status: "revoked",
            accountState: "revoked",
            linkedAt: 1,
          },
        ],
      });
    if (path.startsWith("/api/v3/task-center/")) return Response.json({ rules: null });
    if (path.startsWith("/api/v2/tasks/"))
      return Response.json({ metadata: { taskId: path.split("/").at(-1) } });
    if (path.startsWith("/api/v2/results?"))
      return Response.json({ contractVersion: C, items: [], nextCursor: null });
    if (path.includes("?limit="))
      return Response.json({
        contractVersion: C,
        profile: "folioview.persistent-content.v1",
        items: [metadata],
        nextCursor: null,
      });
    if (o.method === "PATCH") {
      assert.equal(o.headers["Idempotency-Key"], "original_state_operation_0001");
      metadata = {
        ...metadata,
        ...o.json.command.changes,
        stateVersion: metadata.stateVersion + 1,
      };
      return Response.json(metadata);
    }
    return Response.json({
      metadata,
      envelope: { ciphertext: "opaque" },
      manifest: {},
      identity: {},
      binding: {},
      receipt: {},
    });
  };
  const window = {
    location: {
      get hash() {
        return hash;
      },
      pathname: "/tasks",
      search: "",
    },
    history: {
      replaceState() {
        hash = "";
      },
    },
    addEventListener: (k, f) => events.set(k, f),
    removeEventListener: (k) => events.delete(k),
  };
  const document = {
    get visibilityState() {
      return visible ? "visible" : "hidden";
    },
    addEventListener: (k, f) => docEvents.set(k, f),
    removeEventListener: (k) => docEvents.delete(k),
  };
  const module = compile(
    "../components/useTaskResults.ts",
    {
      react,
      "./AuthProvider": {
        useAuth: () => ({ status: "authenticated", sessionKey: owner, requestPrivate }),
      },
      "@/lib/workspace-cache": cache,
      "@/lib/report-provider-attribution": compile("../lib/report-provider-attribution.ts"),
      "@/lib/inbox-link": {
        ...links,
        clearInboxResultLink: () => {
          hash = "";
        },
      },
      "@/lib/inbox-types": inbox,
      "@/lib/task-result-reader": reader,
    },
    {
      window,
      document,
      Response,
      TextDecoder,
      TextEncoder,
      Uint8Array,
      AbortController,
      setTimeout: timers
        ? (fn, ms) => {
            const id = {};
            timers.set(id, { fn, ms });
            return id;
          }
        : setTimeout,
      clearTimeout: timers ? (id) => timers.delete(id) : clearTimeout,
      Date: clock,
    },
  );
  function render() {
    let result,
      n = 0;
    do {
      assert.ok(n++ < 50, "render loop");
      dirty = false;
      index = 0;
      result = module.useTaskResults(
        workspace,
        {
          views: [],
        },
        model,
        active,
        observed,
        center,
        undefined,
        resultsVisible,
      );
      const pendingEffects = effects.splice(0);
      // React runs all previous passive cleanups before the new setups.
      for (const e of pendingEffects) cells[e.n]?.cleanup?.();
      for (const e of pendingEffects) cells[e.n] = { deps: e.deps, cleanup: e.f() };
    } while (dirty);
    return result;
  }
  return {
    render,
    workspace,
    model,
    calls,
    showResults(v) {
      resultsVisible = v;
    },
    observe(v) {
      observed = v;
    },
    events,
    async ready() {
      for (let i = 0; i < 10; i++) {
        render();
        await tick();
      }
      return render();
    },
    stats: () => ({ signs, decrypts }),
    active(v) {
      active = v;
    },
    owner(v) {
      owner = v;
      workspace.owner = v;
      workspace.vaultGeneration++;
    },
    link(v) {
      hash = v;
      events.get("hashchange")?.();
    },
    hidden(hidden = true) {
      visible = !hidden;
      docEvents.get("visibilitychange")?.();
    },
    close() {
      for (const c of cells) c?.cleanup?.();
    },
  };
}
test("task reports read the persistent feed and retire old bookmarks locally", async () => {
  const h = harness();
  try {
    const initial = await h.ready();
    assert.equal(initial.rows[0].kind, "persistent");
    assert.equal(initial.retiredReportLink, false);
    h.link("#inbox/result/old_foreground_fixture");
    const retired = await h.ready();
    assert.equal(retired.retiredReportLink, true);
    assert.equal(retired.error, "");
    assert.equal(
      h.calls.some((call) => call.path.startsWith("/api/v2/results")),
      false,
    );
    h.workspace.phase = "locked";
    assert.equal((await h.ready()).retiredReportLink, true);
    h.link("");
    assert.equal((await h.ready()).retiredReportLink, false);
  } finally {
    h.close();
  }
});
test("returning to a fresh Reports tab preserves its list without another read", async () => {
  const h = harness();
  try {
    const original = await h.ready();
    assert.equal(original.rows[0].kind, "persistent");
    const requestCount = h.calls.length;
    h.hidden();
    assert.equal(h.render().rows.length, 0);
    h.hidden(false);
    const resumed = await h.ready();
    assert.deepEqual(resumed.rows, original.rows);
    assert.equal(h.calls.length, requestCount);
  } finally {
    h.close();
  }
});

test("title preload never marks read; presentation performs exactly one signed update, and history retains the original Agent", async () => {
  const h = harness();
  let m = await h.ready();
  assert.equal(h.stats().decrypts, 0, "overview does not preload private report bodies");
  m.wantTitle(m.rows[0]);
  m = await h.ready();
  assert.equal(m.title(m.rows[0]), "PRIVATE_REPORT");
  assert.equal(h.stats().signs, 0);
  assert.equal(m.unreadCounts.task_A, 1);
  assert.equal(m.providerFor(m.rows[0]), "muse");
  await m.open(m.rows[0]);
  m = h.render();
  assert.equal(h.stats().signs, 0);
  m.presented(m.detail);
  m = await h.ready();
  assert.equal(h.stats().signs, 1);
  assert.equal(m.unreadCounts.task_A, undefined);
  assert.equal(m.detail.row.metadata.read, true);
  assert.equal(h.stats().decrypts, 1);
  h.close();
});
test("returning to a loaded task preserves filters and avoids reloading metadata or decrypting titles", async () => {
  const h = harness();
  let m = await h.ready();
  m.setFilter({ actor: "muse", filter: "unread", query: "PRIVATE" });
  m = h.render();
  const calls = h.calls.length,
    decrypts = h.stats().decrypts;
  h.active(false);
  m = h.render();
  assert.equal(m.rows.length, 0);
  h.active(true);
  m = await h.ready();
  assert.equal(m.filters.query, "PRIVATE");
  assert.equal(h.calls.filter((c) => c.path.includes("?limit=")).length, 1);
  assert.equal(h.stats().decrypts, decrypts);
  assert.ok(h.calls.length >= calls);
  h.close();
});
test("unknown result-state writes retain the original signature and do not allow a replacement mutation", async () => {
  let lost = true;
  const h = harness({
    transport: async (path, o, metadata) => {
      if (o.method === "PATCH" && lost) {
        lost = false;
        throw Error("lost response");
      }
    },
  });
  let m = await h.ready();
  await m.open(m.rows[0]);
  m = h.render();
  await m.change(m.detail.row, { starred: true });
  m = h.render();
  assert.equal(m.pending, true);
  assert.equal(h.stats().signs, 1);
  await m.change(m.detail.row, { archived: true });
  assert.equal(h.stats().signs, 1);
  m.retryState();
  m = await h.ready();
  assert.equal(m.pending, false);
  assert.equal(h.stats().signs, 1);
  const writes = h.calls.filter((c) => c.options.method === "PATCH");
  assert.equal(writes.length, 2);
  assert.deepEqual(writes[0].options.json, writes[1].options.json);
  h.close();
});
test("lock and owner changes mask private titles/details immediately and ignore late work", async () => {
  const h = harness();
  let m = await h.ready();
  const row = m.rows[0];
  await m.open(row);
  h.workspace.phase = "locked";
  m = h.render();
  assert.equal(m.detail, null);
  assert.equal(m.rows.length, 0);
  assert.equal(m.title(row), null);
  h.owner("owner_B");
  m = h.render();
  assert.equal(m.detail, null);
  h.close();
});
test("persistent report bookmarks resolve the owning visible task before opening a modal", async () => {
  const h = harness();
  await h.ready();
  h.model.selected = { taskId: "task_B", taskVersion: 1 };
  h.link("#inbox/result/presult_A/revisions/1");
  const m = await h.ready();
  assert.equal(h.model.selected.taskId, "task_A");
  assert.equal(m.detail.row.metadata.resultId, "presult_A");
  assert.equal(h.stats().signs, 0);
  m.close();
  h.close();
});

test("read-only presentation does not consume the later ability to acknowledge a report", async () => {
  const h = harness();
  let m = await h.ready();
  await m.open(m.rows[0]);
  h.workspace.canWriteState = false;
  m = h.render();
  m.presented(m.detail);
  assert.equal(h.stats().signs, 0);
  h.workspace.canWriteState = true;
  m = h.render();
  m.presented(m.detail);
  await h.ready();
  assert.equal(h.stats().signs, 1);
  h.close();
});

test("initial result metadata reads one persistent page and no private report bodies", async () => {
  const h = harness({
    transport: async (path) =>
      path.includes("?limit=")
        ? Response.json({
            contractVersion: C,
            ...(path.includes("persistent-results")
              ? { profile: "folioview.persistent-content.v1" }
              : {}),
            items: [],
            nextCursor: path.includes("persistent-results")
              ? "pidx_" + "a".repeat(64) + ":1"
              : "next",
          })
        : undefined,
  });
  let m = await h.ready();
  assert.equal(h.calls.filter((c) => c.path.includes("?limit=")).length, 1);
  assert.equal(m.hasMore, true);
  assert.equal(m.partial, true);
  assert.equal(h.stats().decrypts, 0);
  await m.more();
  m = h.render();
  assert.equal(h.calls.filter((c) => c.path.includes("?limit=")).length, 2);
  h.close();
});

test("selected task history shares verified center state and pages only after explicit More", async () => {
  const h = harness({
    center: { selectedRecord: { taskId: "task_A", rules: {} } },
    transport: async (path, options) => {
      if (path.endsWith("/results/query"))
        return Response.json({
          contractVersion: C,
          profile: "folioview.task-center.v1",
          items: [
            {
              kind: "persistent",
              metadata: {
                ...meta(),
                resultId: options.json.request.cursor ? "presult_older" : "presult_first",
              },
              triggerKind: "manual",
              attribution: { provider: "chatgpt" },
            },
          ],
          nextCursor: options.json.request.cursor ? null : "older",
        });
    },
  });
  let m = await h.ready();
  assert.equal(h.calls.filter((c) => c.path.endsWith("/results/query")).length, 1);
  assert.equal(
    h.calls.some((c) => c.path === "/api/v3/task-center/vault_A/tasks/task_A"),
    false,
  );
  assert.ok(m.allTaskRows.some((r) => r.metadata.resultId === "presult_first"));
  const first = m.allTaskRows.find((r) => r.metadata.resultId === "presult_first");
  assert.equal(m.providerFor(first), "chatgpt");
  assert.equal(first.triggerKind, "manual");
  assert.equal(m.hasMore, true);
  assert.equal(m.complete, false);
  await m.more();
  m = h.render();
  assert.equal(h.calls.filter((c) => c.path.endsWith("/results/query")).length, 2);
  assert.ok(m.allTaskRows.some((r) => r.metadata.resultId === "presult_older"));
  assert.equal(m.complete, true);
  h.active(false);
  h.render();
  h.active(true);
  await h.ready();
  assert.equal(h.calls.filter((c) => c.path.endsWith("/results/query")).length, 2);
  h.close();
});

test("a malformed selected page publishes neither foreign rows nor invented trigger attribution", async () => {
  const h = harness({
    center: { selectedRecord: { taskId: "task_A", rules: {} } },
    transport: async (path) =>
      path.endsWith("/results/query")
        ? Response.json({
            contractVersion: C,
            profile: "folioview.task-center.v1",
            items: [
              {
                kind: "persistent",
                metadata: { ...meta(), taskId: "task_FOREIGN" },
                triggerKind: "manual",
              },
            ],
            nextCursor: null,
          })
        : undefined,
  });
  const m = await h.ready();
  assert.equal(m.error, "invalid_response");
  assert.equal(m.allTaskRows.length, 1);
  assert.equal(m.allTaskRows[0].triggerKind, "legacy_unknown");
  assert.equal(m.complete, false);
  h.close();
});

test("ignored result transport and body cancellation settle after the request deadline", async () => {
  for (const stuck of ["transport", "body"]) {
    const timers = new Map();
    const h = harness({
      timers,
      transport: async (path) =>
        path.includes("?limit=")
          ? stuck === "transport"
            ? new Promise(() => {})
            : {
                ok: true,
                headers: new Headers(),
                body: {
                  getReader: () => ({
                    read: () => new Promise(() => {}),
                    cancel: async () => {},
                    releaseLock() {},
                  }),
                },
              }
          : undefined,
    });
    h.render();
    await tick();
    for (const t of [...timers.values()].filter((t) => t.ms === 14000)) t.fn();
    await tick();
    const m = h.render();
    assert.equal(m.loading, false);
    assert.equal(m.error, "request_timeout");
    assert.equal(m.complete, false);
    h.close();
  }
});

test("expired result metadata refreshes the head instead of continuing an old cursor", async () => {
  let now = 100000;
  const h = harness({
    clock: class extends Date {
      static now() {
        return now;
      }
    },
    center: { selectedRecord: { taskId: "task_A", rules: {} } },
    transport: async (path, options) => {
      if (path.endsWith("/results/query"))
        return Response.json({
          contractVersion: C,
          profile: "folioview.task-center.v1",
          items: [],
          nextCursor: "older-selected",
        });
      if (path.includes("?limit="))
        return Response.json({
          contractVersion: C,
          ...(path.includes("persistent-results")
            ? { profile: "folioview.persistent-content.v1" }
            : {}),
          items: [],
          nextCursor: path.includes("persistent-results")
            ? "pidx_" + "b".repeat(64) + ":1"
            : "older-global",
        });
    },
  });
  await h.ready();
  h.active(false);
  h.render();
  now += 30001;
  h.active(true);
  await h.ready();
  const globals = h.calls.filter((c) => c.path.includes("?limit="));
  assert.equal(globals.length, 2);
  assert.ok(
    globals.every((c) => !c.path.includes("cursor=")),
    JSON.stringify(globals.map((c) => c.path)),
  );
  const selected = h.calls.filter((c) => c.path.endsWith("/results/query"));
  assert.equal(selected.length, 2);
  assert.ok(selected.every((c) => c.options.json.request.cursor === null));
  h.close();
});

test("new results arriving during initial loading queue one fresh head read without losing the notification", async () => {
  let release;
  const blocked = new Promise((resolve) => {
    release = resolve;
  });
  let first = true;
  const h = harness({
    transport: async (path) => {
      if (path.includes("persistent-results/") && path.includes("?limit=") && first) {
        first = false;
        return blocked;
      }
    },
  });
  h.render();
  await tick();
  h.observe("presult_new");
  h.render();
  await tick();
  release(
    Response.json({
      contractVersion: C,
      profile: "folioview.persistent-content.v1",
      items: [],
      nextCursor: null,
    }),
  );
  await h.ready();
  assert.equal(h.calls.filter((c) => c.path.includes("?limit=")).length, 2);
  assert.equal(h.render().loading, false);
  h.close();
});

test("a run result reported during loading needs no refresh when the pending feed already contains it", async () => {
  let release;
  const h = harness({
    transport: (p) => {
      if (p.includes("persistent-results/") && p.includes("?limit="))
        return new Promise((resolve) => {
          release = resolve;
        });
    },
  });
  try {
    h.render();
    await tick();
    h.observe("presult_A");
    h.render();
    release(
      Response.json({
        contractVersion: C,
        profile: "folioview.persistent-content.v1",
        items: [meta()],
        nextCursor: null,
      }),
    );
    const r = await h.ready();
    assert.equal(h.calls.filter((c) => c.path.includes("?limit=")).length, 1);
    assert.equal(r.unreadCounts.task_A, 1);
  } finally {
    h.close();
  }
});
test("each newly reported ID refreshes once, a failed read waits for recovery, and a new Owner checks independently", async () => {
  let items = [meta()],
    fail = false;
  const h = harness({
    transport: (p) => {
      if (p.includes("persistent-results/") && p.includes("?limit="))
        return fail
          ? Response.json({}, { status: 503 })
          : Response.json({
              contractVersion: C,
              profile: "folioview.persistent-content.v1",
              items,
              nextCursor: null,
            });
    },
  });
  const count = () => h.calls.filter((c) => c.path.includes("?limit=")).length;
  try {
    await h.ready();
    h.observe("presult_A");
    await h.ready();
    assert.equal(count(), 1);
    items = [meta(), { ...meta(), resultId: "presult_new" }];
    h.observe("presult_A|presult_new");
    let r = await h.ready();
    assert.equal(count(), 2);
    assert.equal(r.unreadCounts.task_A, 2);
    fail = true;
    h.observe("presult_A|presult_new|presult_unknown");
    r = await h.ready();
    assert.ok(r.error);
    await h.ready();
    assert.equal(count(), 3);
    h.observe("presult_new|presult_unknown");
    await h.ready();
    assert.equal(count(), 3);
    fail = false;
    items = [];
    h.owner("owner_B");
    r = await h.ready();
    assert.equal(count(), 5);
    assert.equal(r.unreadCounts.task_A, undefined);
    await h.ready();
    assert.equal(count(), 5);
  } finally {
    h.close();
  }
});

test("a second result noticed during a forced refresh is checked after the pending response", async () => {
  let readCount = 0,
    release;
  const item = (id) => ({ ...meta(), resultId: id });
  const reply = (ids) =>
    Response.json({
      contractVersion: C,
      profile: "folioview.persistent-content.v1",
      items: ids.map(item),
      nextCursor: null,
    });
  const h = harness({
    transport: (path) => {
      if (!path.includes("persistent-results/") || !path.includes("?limit=")) return;
      readCount++;
      if (readCount === 1) return reply(["presult_A"]);
      if (readCount === 2)
        return new Promise((resolve) => {
          release = resolve;
        });
      return reply(["presult_A", "presult_B", "presult_C"]);
    },
  });
  try {
    await h.ready();
    h.observe("presult_B");
    h.render();
    await tick();
    h.observe("presult_B|presult_C");
    h.render();
    await tick();
    assert.equal(readCount, 2);
    release(reply(["presult_A", "presult_B"]));
    const r = await h.ready();
    assert.equal(r.unreadCounts.task_A, 3);
    assert.equal(readCount, 3);
    await h.ready();
    assert.equal(readCount, 3);
  } finally {
    h.close();
  }
});

test("task-specific results wait for the results tab and a matching verified task", async () => {
  const center = { selectedRecord: { taskId: "task_B", rules: {} } };
  const h = harness({
    resultsVisible: false,
    center,
    transport: (path) =>
      path.endsWith("/results/query")
        ? Response.json({
            contractVersion: C,
            profile: "folioview.task-center.v1",
            items: [],
            nextCursor: null,
          })
        : undefined,
  });
  const count = () => h.calls.filter((c) => c.path.endsWith("/results/query")).length;
  try {
    assert.equal((await h.ready()).complete, false);
    h.showResults(true);
    let model = await h.ready();
    await model.reload();
    model = await h.ready();
    await model.more();
    assert.equal((await h.ready()).complete, false);
    assert.equal(count(), 0);
    h.showResults(false);
    center.selectedRecord = { taskId: "task_A", rules: {} };
    await h.ready();
    assert.equal(count(), 0);
    h.showResults(true);
    await h.ready();
    assert.equal(count(), 1);
  } finally {
    h.close();
  }
});
test("a task entering the new result route refreshes despite a fresh legacy display cache", async () => {
  const center = { selectedRecord: { taskId: "task_A", rules: null } };
  const h = harness({
    center,
    transport: async (path) =>
      path.endsWith("/results/query")
        ? Response.json({
            contractVersion: C,
            profile: "folioview.task-center.v1",
            items: [],
            nextCursor: null,
          })
        : undefined,
  });
  await h.ready();
  assert.equal(h.calls.filter((c) => c.path.endsWith("/results/query")).length, 0);
  center.selectedRecord = { taskId: "task_A", rules: {} };
  await h.ready();
  assert.equal(h.calls.filter((c) => c.path.endsWith("/results/query")).length, 1);
  h.close();
});

test("legacy report providers load independently of Agent discovery, retain revoked history and never infer a foreign vault or unknown actor", async () => {
  const h = harness();
  let m = await h.ready();
  const row = m.rows[0];
  assert.equal(m.providerFor(row), "muse");
  assert.equal(
    m.providerFor({
      ...row,
      metadata: { ...row.metadata, connectionId: "unknown_chatgpt_client" },
    }),
    "agent",
  );
  assert.equal(h.calls.filter((c) => c.path === "/api/v2/persistent-connections").length, 1);
  assert.ok(
    !h.calls.some((c) => /capabilities|credentials|provider-connections|vaults/.test(c.path)),
  );
  assert.equal(
    m.providerFor({ ...row, metadata: { ...row.metadata, connectionId: "__proto__" } }),
    "agent",
  );
  const oldProvider = m.providerFor;
  h.workspace.vault = { ...h.workspace.vault, vaultId: "vault_B" };
  h.workspace.vaultGeneration++;
  m = await h.ready();
  assert.equal(m.providerFor(m.rows[0]), "agent");
  assert.equal(oldProvider(row), "agent");
  h.close();
});

test("provider lookup loading/failure cannot become completed results or erase real unread counts", async () => {
  let resolve,
    fail = false;
  const gate = new Promise((r) => (resolve = r));
  const h = harness({
    transport: (path) =>
      path === "/api/v2/persistent-connections"
        ? fail
          ? Response.json({}, { status: 503 })
          : gate
        : undefined,
  });
  let m = await h.ready();
  assert.equal(m.unreadCounts.task_A, 1);
  assert.equal(m.loading, true);
  assert.equal(m.complete, false);
  assert.equal(m.providerFor(m.rows[0]), "agent");
  resolve(
    Response.json({
      contractVersion: C,
      profile: "folioview.persistent-account.v1",
      connections: [],
    }),
  );
  m = await h.ready();
  assert.equal(m.complete, true);
  assert.equal(m.providerFor(m.rows[0]), "agent");
  fail = true;
  await m.reload();
  m = h.render();
  assert.equal(m.error, "request_failed");
  assert.equal(m.complete, false);
  assert.equal(m.unreadCounts.task_A, 1);
  h.close();
});

test("late provider replies cannot label another Owner or unlock generation and route reentry reuses the scoped map", async () => {
  let resolve,
    held = true;
  const gate = new Promise((r) => (resolve = r));
  const h = harness({
    transport: (path) => (path === "/api/v2/persistent-connections" && held ? gate : undefined),
  });
  await h.ready();
  held = false;
  h.owner("owner_B");
  let m = await h.ready();
  assert.equal(m.providerFor(m.rows[0]), "muse");
  resolve(
    Response.json({
      contractVersion: C,
      profile: "folioview.persistent-account.v1",
      connections: [
        {
          connectionId: "connection_A",
          clientId: "client_A",
          vaultId: "vault_A",
          provider: "chatgpt",
          status: "active",
          accountState: "connected",
          linkedAt: 1,
        },
      ],
    }),
  );
  m = await h.ready();
  assert.equal(m.providerFor(m.rows[0]), "muse");
  const count = h.calls.filter((c) => c.path === "/api/v2/persistent-connections").length;
  h.active(false);
  h.render();
  h.active(true);
  m = await h.ready();
  assert.equal(h.calls.filter((c) => c.path === "/api/v2/persistent-connections").length, count);
  assert.equal(m.providerFor(m.rows[0]), "muse");
  h.close();
});
