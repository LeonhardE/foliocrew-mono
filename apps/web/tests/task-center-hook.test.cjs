const test = require("node:test"),
  assert = require("node:assert/strict");
const { compile, settle } = require("./resource-library-helpers.cjs");
const CONTRACT = "folioview.agent-workspace.v2.0";
const meta = (taskId = "task_A", patch = {}) => ({
  taskId,
  taskVersion: 1,
  executionEpoch: 1,
  status: "active",
  envelopeFingerprint: "fingerprint_A",
  resourceBindings: [],
  ...patch,
});
const state = (taskId = "task_A", patch = {}) => ({
  contractVersion: CONTRACT,
  taskId,
  taskVersion: 1,
  executionEpoch: 1,
  rules: null,
  assignments: [],
  ...patch,
});
function harness({
  pending = new Map(),
  transport,
  timers,
  document = Object.assign(new EventTarget(), { visibilityState: "visible" }),
  initial = meta(),
  overview,
  selectedDetail,
} = {}) {
  let selected = initial;
  let owner = "owner_A",
    index = 0,
    dirty = false;
  const cells = [],
    effects = [],
    calls = [];
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
          const value = typeof next === "function" ? next(cells[n].value) : next;
          dirty ||= !Object.is(value, cells[n].value);
          cells[n].value = value;
        },
      ];
    },
    useCallback(v, deps) {
      const n = index++;
      if (!cells[n] || changed(cells[n].deps, deps)) cells[n] = { deps, value: v };
      return cells[n].value;
    },
    useEffect(f, deps) {
      const n = index++;
      if (!cells[n] || changed(cells[n].deps, deps)) effects.push({ n, f, deps });
    },
  };
  const requestPrivate = async (_s, path, _o, options) => {
    calls.push({ path, options });
    const special = await transport?.(path, options, pending);
    if (special) return special;
    return Response.json(
      path.endsWith("capabilities")
        ? { enabled: true }
        : path.endsWith("/manual")
          ? { items: [] }
          : state(path.split("/").at(-1)),
    );
  };
  const workspace = {
    owner,
    phase: "unlocked",
    canWriteState: true,
    vault: {
      vaultId: "vault_A",
      rootKeyId: "root_A",
      version: 1,
      archive: { ownerSubject: "subject_A" },
    },
    vaultGeneration: 1,
    verifyTaskCenterState: async (s) => s,
    loadTaskCenterPending: async (t) => pending.get(t) ?? null,
    prepareTaskCenterControl: async (args) => {
      const p = {
        taskId: args.state.taskId,
        operationId: "center_01234567890123456789012345678901",
        action: args.action,
        body: {
          contractVersion: CONTRACT,
          command: { protected: "p", payload: "q", signature: "s" },
        },
      };
      pending.set(p.taskId, p);
      return p;
    },
    finishTaskCenterPending: async (t) => pending.delete(t),
  };
  const m = compile(
    "../components/useTaskCenter.ts",
    {
      react,
      "./AuthProvider": {
        useAuth: () => ({ status: "authenticated", sessionKey: owner, requestPrivate }),
      },
    },
    {
      Response,
      AbortController,
      setTimeout: timers
        ? (fn, ms) => {
            const id = {};
            timers.set(id, { fn, ms });
            return id;
          }
        : setTimeout,
      clearTimeout: timers ? (id) => timers.delete(id) : clearTimeout,
      setInterval,
      clearInterval,
      TextEncoder,
      TextDecoder,
      Uint8Array,
      Date,
      document,
      crypto: require("node:crypto").webcrypto,
    },
  );

  function render() {
    let result,
      n = 0;
    do {
      assert.ok(n++ < 30, "render loop");
      dirty = false;
      index = 0;
      result = m.useTaskCenter(workspace, true, selected, overview, selectedDetail);
      for (const e of effects.splice(0)) {
        cells[e.n]?.cleanup?.();
        cells[e.n] = { deps: e.deps, cleanup: e.f() };
      }
    } while (dirty);
    return result;
  }
  return {
    select(value) {
      selected = value;
    },
    pending,
    calls,
    workspace,
    render,
    async ready() {
      for (let n = 0; n < 4; n++) {
        render();
        await settle();
      }
      return render();
    },
    owner(v) {
      owner = v;
      workspace.owner = v;
      workspace.vaultGeneration++;
    },
    close() {
      for (const c of cells) c?.cleanup?.();
    },
  };
}
test("unknown task saves survive remount without an automatic replacement or resend", async () => {
  const pending = new Map();
  const transport = async (path, o, p) => {
    if (o.method === "POST") {
      assert.ok(p.has("task_A"), "encrypted outbox must precede transport");
      throw Error("lost response");
    }
  };
  const h = harness({ pending, transport });
  let m = await h.ready();
  await assert.rejects(m.command("task_A", "set_rules", null));
  assert.equal(pending.size, 1);
  h.close();
  const restored = harness({
    pending,
    transport: async (path) =>
      path.includes("/operations/") ? Response.json({ original: true }) : undefined,
  });
  m = await restored.ready();
  assert.ok(m.pending);
  assert.equal(restored.calls.filter((c) => c.options.method === "POST").length, 0);
  await m.recover("task_A");
  m = await restored.ready();
  assert.equal(m.pending, null);
  assert.equal(pending.size, 0);
  restored.close();
});
test("safe abandonment addresses the original operation with its signing-input fingerprint", async () => {
  const h = harness({
    transport: async (path, o) => {
      if (path.endsWith("/commands")) throw Error("offline");
      if (path.endsWith("/cancel")) {
        assert.match(o.json.fingerprint, /^[a-f0-9]{64}$/);
        return Response.json({ state: "cancelled" });
      }
    },
  });
  let m = await h.ready();
  await assert.rejects(m.command("task_A", "set_rules", null));
  m = await h.ready();
  await m.recover("task_A", false, true);
  assert.equal(h.pending.size, 0);
  assert.equal(h.calls.filter((c) => c.path.endsWith("/commands")).length, 1);
  h.owner("owner_B");
  m = h.render();
  assert.deepEqual(Object.keys(m.records), []);
  assert.equal(m.pending, null);
  h.close();
});

test("ignored command abort settles the UI and keeps its original pending packet without replay", async () => {
  const timers = new Map();
  const h = harness({
    timers,
    transport: async (_path, options) =>
      options.method === "POST" ? new Promise(() => {}) : undefined,
  });
  const model = await h.ready();
  const saving = model.command("task_A", "set_rules", null);
  const rejected = assert.rejects(saving, /request_timeout/);
  await settle();
  assert.equal(h.pending.size, 1);
  const timer = [...timers.values()].find((v) => v.ms === 14000);
  assert.ok(timer);
  timer.fn();
  await rejected;
  assert.equal(h.render().busy, false);
  assert.equal(h.pending.size, 1);
  await assert.rejects(h.render().command("task_A", "set_rules", null), /operation_pending/);
  await h.ready();
  assert.equal(h.calls.filter((c) => c.options.method === "POST").length, 1);
  h.close();
});

test("manual history leaves a display slot free until the task state has been verified", async () => {
  let release;
  const blocked = new Promise((resolve) => {
    release = resolve;
  });
  const h = harness({
    transport: async (path) => (path.endsWith("/tasks/task_A") ? blocked : undefined),
  });
  h.render();
  await settle();
  assert.ok(
    !h.calls.some((call) => call.path.endsWith("/manual")),
    "secondary run history must not take a slot ahead of state or the selected task body",
  );
  assert.equal(h.render().records.task_A, undefined);
  release(Response.json(state()));
  const m = await h.ready();
  assert.ok(m.records.task_A);
  assert.equal(m.runState, "ready");
  assert.equal(countCalls(h, "/manual"), 1);
  h.close();
});

test("capability receipt distinguishes loading legitimate disabled failure and a new Owner", async () => {
  let release,
    fail = false;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const h = harness({
    transport: (path) =>
      path.endsWith("capabilities")
        ? fail
          ? Response.json({}, { status: 503 })
          : gate
        : undefined,
  });
  try {
    assert.equal(h.render().capabilityState, "loading");
    release(Response.json({ enabled: false }));
    let model = await h.ready();
    assert.equal(model.capabilityState, "ready");
    assert.equal(model.enabled, false);
    fail = true;
    h.owner("owner_B");
    assert.equal(h.render().capabilityState, "loading");
    model = await h.ready();
    assert.equal(model.capabilityState, "error");
    assert.equal(model.enabled, false);
  } finally {
    h.close();
  }
});

const binding = { ref: { kind: "watchlist", resourceId: "synth" }, sourceEpoch: 1 };
const modern = (id, provider) =>
  state(id, {
    rules: { definition: { taskVersion: 1, executionEpoch: 1 } },
    assignments: provider
      ? [{ assignment: { status: "active", provider }, plan: { currentAssignment: true } }]
      : [],
  });
const legacyAuthority = (task, overrides = {}) => ({
  contractVersion: CONTRACT,
  profile: "folioview.persistent-content.v1",
  envelope: {},
  authority: {
    context: {
      ownerSubject: "subject_A",
      vaultId: "vault_A",
      rootKeyId: "root_A",
      objectType: "task",
      objectId: task.taskId,
      taskId: task.taskId,
      taskVersion: task.taskVersion,
      executionEpoch: task.executionEpoch,
      ownerTaskFingerprint: task.envelopeFingerprint,
      connectionId: "connection_A",
      ...overrides,
    },
  },
});
const connectionList = {
  contractVersion: CONTRACT,
  profile: "folioview.persistent-account.v1",
  connections: [
    {
      connectionId: "connection_A",
      clientId: "client_A",
      vaultId: "vault_A",
      provider: "muse",
      status: "active",
      accountState: "connected",
      linkedAt: 1,
    },
  ],
};
const countCalls = (h, end) => h.calls.filter((c) => c.path.endsWith(end)).length;
function mappedOverview() {
  const receipt = {
    scope: "owner_A:vault_A:1:1",
    at: Date.now(),
    data: { vaultId: "vault_A", capabilities: { enabled: true }, connections: connectionList },
  };
  return {
    receipt,
    acquireWithFallback: async () => receipt,
    invalidate() {
      assert.fail("passive detail reads discarded the shared overview");
    },
  };
}

test("verified current assignments and confirmed empty tasks do not read legacy authority or discover connections", async () => {
  const a = meta("task_A", { resourceBindings: [binding] }),
    b = meta("task_B"),
    c = meta("task_C", { resourceBindings: [binding] });
  const h = harness({
    initial: a,
    transport: (path) =>
      path.endsWith("/tasks/task_A")
        ? Response.json(modern("task_A", "chatgpt"))
        : path.endsWith("/tasks/task_C")
          ? Response.json(modern("task_C", null))
          : undefined,
  });
  try {
    let m = await h.ready();
    assert.equal(m.executors.status, "ready");
    assert.deepEqual(Array.from(m.executors.providers), ["chatgpt"]);
    h.select(b);
    m = await h.ready();
    assert.deepEqual(Array.from(m.executors.providers), []);
    assert.equal(m.executors.status, "ready");
    h.select(c);
    m = await h.ready();
    assert.deepEqual(Array.from(m.executors.providers), []);
    assert.equal(m.executors.status, "ready");
    h.select(a);
    m = await h.ready();
    assert.deepEqual(Array.from(m.executors.providers), ["chatgpt"]);
    assert.equal(countCalls(h, "/tasks/task_A"), 1);
    assert.equal(countCalls(h, "/authority"), 0);
    assert.equal(countCalls(h, "/persistent-connections"), 0);
  } finally {
    h.close();
  }
});

test("a legacy assignment reads its original authority once and reuses matching overview labels without opening its body or refreshing the vault", async () => {
  const task = meta("task_A", { resourceBindings: [binding] });
  const h = harness({
    initial: task,
    overview: mappedOverview(),
    transport: (path) =>
      path.endsWith("/authority") ? Response.json(legacyAuthority(task)) : undefined,
  });
  try {
    const m = await h.ready();
    assert.equal(m.executors.status, "ready");
    assert.deepEqual(Array.from(m.executors.providers), ["muse"]);
    assert.deepEqual(
      h.calls.map((c) => c.path).sort(),
      [
        "/api/v3/task-center/vault_A/tasks/task_A",
        "/api/v3/task-center/vault_A/tasks/task_A/manual",
        "/api/v2/persistent-content/vault_A/tasks/task_A/authority",
      ].sort(),
    );
    h.select(meta("task_B"));
    await h.ready();
    h.select(task);
    await h.ready();
    assert.equal(countCalls(h, "/authority"), 1);
  } finally {
    h.close();
  }
});

test("a legacy failure stays in the executor field and retries just its read; missing or older authority is confirmed empty", async () => {
  const task = meta("task_A", { resourceBindings: [binding], taskVersion: 2 });
  let fail = true,
    old = false;
  const h = harness({
    initial: task,
    transport: (path) =>
      path.endsWith("/tasks/task_A")
        ? Response.json(state("task_A", { taskVersion: 2 }))
        : path.endsWith("/authority")
          ? fail
            ? Response.json({}, { status: 503 })
            : Response.json(
                old
                  ? legacyAuthority(task, { taskVersion: 1 })
                  : {
                      contractVersion: CONTRACT,
                      profile: "folioview.persistent-content.v1",
                      authority: null,
                      envelope: null,
                    },
              )
          : undefined,
  });
  try {
    let m = await h.ready();
    assert.equal(m.error, "");
    assert.equal(m.executors.status, "error");
    fail = false;
    m.retryExecutors();
    m = await h.ready();
    assert.equal(m.executors.status, "ready");
    assert.deepEqual(Array.from(m.executors.providers), []);
    assert.equal(countCalls(h, "/authority"), 2);
    assert.equal(countCalls(h, "/tasks/task_A"), 1);
    old = true;
    await m.load(task.taskId, true);
    m = await h.ready();
    assert.equal(m.executors.status, "ready");
    assert.deepEqual(Array.from(m.executors.providers), []);
    assert.equal(countCalls(h, "/persistent-connections"), 0);
  } finally {
    h.close();
  }
});

test("legacy authority and mapping stay bound to the selected owner, vault, version and fingerprint across rapid switching", async () => {
  const task = meta("task_A", { resourceBindings: [binding] });
  let release,
    wrong = false;
  const delayed = new Promise((r) => {
    release = r;
  });
  const overview = mappedOverview();
  overview.receipt.scope = "owner_B:vault_A:1:1";
  const h = harness({
    initial: task,
    overview,
    transport: (path) =>
      path.endsWith("/authority")
        ? wrong
          ? Response.json(legacyAuthority(task, { ownerTaskFingerprint: "wrong" }))
          : delayed
        : path.endsWith("/persistent-connections")
          ? Response.json(connectionList)
          : undefined,
  });
  try {
    let m = await h.ready();
    assert.equal(m.executors.status, "loading");
    h.select(meta("task_B"));
    m = await h.ready();
    assert.equal(m.executors.status, "ready");
    assert.deepEqual(Array.from(m.executors.providers), []);
    h.select(task);
    await h.ready();
    release(Response.json(legacyAuthority(task)));
    m = await h.ready();
    assert.deepEqual(Array.from(m.executors.providers), ["muse"]);
    assert.equal(countCalls(h, "/persistent-connections"), 1);
    wrong = true;
    h.owner("owner_B");
    m = await h.ready();
    assert.equal(m.executors.status, "error");
    assert.deepEqual(Array.from(m.executors.providers), []);
    assert.equal(m.error, "");
    assert.equal(countCalls(h, "/persistent-connections"), 1);
  } finally {
    h.close();
  }
});

test("a same-version assignment mutation invalidates the receipt and cannot be overwritten by the older read", async () => {
  let provider = "chatgpt",
    block = false,
    release;
  const wait = new Promise((r) => {
    release = r;
  });
  const h = harness({
    transport: (path, o) => {
      if (path.endsWith("/commands")) {
        provider = "muse";
        return Response.json({});
      }
      if (path.endsWith("/tasks/task_A")) {
        if (block) {
          block = false;
          return wait;
        }
        return Response.json(modern("task_A", provider));
      }
    },
  });
  try {
    let m = await h.ready();
    assert.deepEqual(Array.from(m.executors.providers), ["chatgpt"]);
    block = true;
    const stale = m.load("task_A", true);
    await settle();
    await m.command("task_A", "set_rules", null);
    m = await h.ready();
    assert.deepEqual(Array.from(m.executors.providers), ["muse"]);
    release(Response.json(modern("task_A", "chatgpt")));
    await stale;
    m = await h.ready();
    assert.deepEqual(Array.from(m.executors.providers), ["muse"]);
    assert.equal(m.pending, null);
  } finally {
    h.close();
  }
});

test("slow run history and outbox cannot hold back legacy executor authority", async () => {
  const task = meta("task_A", { resourceBindings: [binding] });
  let releaseManual, releasePending;
  const history = new Promise((resolve) => {
    releaseManual = resolve;
  });
  const outbox = new Promise((resolve) => {
    releasePending = resolve;
  });
  const h = harness({
    initial: task,
    overview: mappedOverview(),
    transport: (path) =>
      path.endsWith("/authority")
        ? Response.json(legacyAuthority(task))
        : path.endsWith("/manual")
          ? history
          : undefined,
  });
  h.workspace.loadTaskCenterPending = () => outbox;
  try {
    let m = await h.ready();
    const paths = h.calls.map((c) => c.path);
    assert.ok(
      paths.findIndex((p) => p.endsWith("/authority")) <
        paths.findIndex((p) => p.endsWith("/manual")),
    );
    assert.deepEqual(Array.from(m.executors.providers), ["muse"]);
    assert.equal(m.runState, "loading");
    await assert.rejects(m.command(task.taskId, "manual_intent", []), /request_failed/);
    releaseManual(Response.json({ items: [{ aggregate: { hasActiveExecutors: true } }] }));
    m = await h.ready();
    assert.equal(m.runState, "loading");
    assert.equal(m.manual[task.taskId][0].aggregate.hasActiveExecutors, true);
    releasePending(null);
    m = await h.ready();
    assert.equal(m.runState, "ready");
    await assert.rejects(m.command(task.taskId, "manual_intent", []), /operation_pending/);
    assert.equal(h.calls.filter((c) => c.options.method === "POST").length, 0);
  } finally {
    h.close();
  }
});

test("run history failure retries locally without rereading verified state or legacy authority", async () => {
  const task = meta("task_A", { resourceBindings: [binding] });
  let broken = true;
  const h = harness({
    initial: task,
    overview: mappedOverview(),
    transport: (path) =>
      path.endsWith("/authority")
        ? Response.json(legacyAuthority(task))
        : path.endsWith("/manual") && broken
          ? Response.json({}, { status: 503 })
          : undefined,
  });
  try {
    let m = await h.ready();
    assert.equal(m.runState, "error");
    assert.equal(m.executors.status, "ready");
    assert.equal(m.error, "");
    broken = false;
    m.retryRunState();
    m = await h.ready();
    assert.equal(m.runState, "ready");
    assert.equal(countCalls(h, "/authority"), 1);
    assert.equal(countCalls(h, "/tasks/task_A"), 1);
    assert.equal(countCalls(h, "/manual"), 2);
  } finally {
    h.close();
  }
});

test("an earlier visit cannot replace the selected outbox or enable a run before the current check", async () => {
  const h = harness();
  const deferred = [];
  const hold = (task) => new Promise((resolve) => deferred.push({ task, resolve }));
  try {
    let m = await h.ready();
    assert.equal(m.runState, "ready");
    h.workspace.loadTaskCenterPending = hold;
    h.select(meta("task_B"));
    m = await h.ready();
    assert.equal(m.runState, "loading");
    h.select(meta());
    m = h.render();
    assert.equal(m.runState, "loading");
    await assert.rejects(m.command("task_A", "manual_intent", []), /request_failed/);
    h.select(meta("task_B"));
    m = await h.ready();
    assert.equal(m.runState, "loading");
    assert.deepEqual(
      deferred.map((v) => v.task),
      ["task_B", "task_A", "task_B"],
    );
    deferred[0].resolve({ taskId: "task_B", operationId: "older_B" });
    deferred[1].resolve({ taskId: "task_A", operationId: "late_A" });
    m = await h.ready();
    assert.equal(m.pending, null);
    assert.equal(m.runState, "loading");
    deferred[2].resolve({ taskId: "task_B", operationId: "current_B" });
    m = await h.ready();
    assert.equal(m.runState, "ready");
    assert.equal(m.pending.operationId, "current_B");
    assert.equal(countCalls(h, "/manual"), 2);
  } finally {
    h.close();
  }
});

test("run confirmation checks the current definition and history together and preserves another client's active run", async () => {
  let confirming = false,
    releaseDefinition,
    releaseHistory;
  const h = harness({
    transport: (path) => {
      if (!confirming) return;
      if (path.endsWith("/tasks/task_A"))
        return new Promise((resolve) => {
          releaseDefinition = resolve;
        });
      if (path.endsWith("/manual"))
        return new Promise((resolve) => {
          releaseHistory = resolve;
        });
    },
  });
  let signed = 0;
  h.workspace.prepareTaskCenterControl = () => {
    signed++;
    throw Error("unexpected signing");
  };
  try {
    let m = await h.ready();
    assert.equal(m.runState, "ready");
    assert.equal(m.manual.task_A.length, 0);
    confirming = true;
    const confirmed = m.command("task_A", "manual_intent", ["agent"]);
    await settle();
    assert.equal(typeof releaseDefinition, "function");
    assert.equal(typeof releaseHistory, "function");
    releaseDefinition(Response.json(state()));
    releaseHistory(
      Response.json({
        items: [
          { snapshot: { requestId: "from_other_device" }, aggregate: { hasActiveExecutors: true } },
        ],
      }),
    );
    await confirmed;
    m = h.render();
    assert.equal(m.manual.task_A[0].snapshot.requestId, "from_other_device");
    assert.equal(m.error, "");
    assert.equal(signed, 0);
    assert.equal(h.calls.filter((c) => c.options.method === "POST").length, 0);
  } finally {
    h.close();
  }
});

test("manual confirmation bounds both reads and abandons them on navigation or expiry before signing", async () => {
  for (const outcome of ["cancel", "deadline"]) {
    const timers = new Map(),
      signals = [];
    let confirming = false;
    const h = harness({
      timers,
      transport: (_path, options) => {
        if (!confirming) return;
        signals.push(options.signal);
        return new Promise(() => {});
      },
    });
    try {
      const m = await h.ready();
      assert.equal(m.runState, "ready");
      confirming = true;
      const confirmation = m.command("task_A", "manual_intent", ["agent"]);
      const rejected = assert.rejects(
        confirmation,
        outcome === "cancel" ? /cancelled/ : /request_timeout/,
      );
      await settle();
      assert.deepEqual(
        [...timers.values()].map((entry) => entry.ms),
        [24000, 24000],
      );
      assert.equal(signals.length, 2);
      assert.ok(signals.every((signal) => !signal.aborted));
      if (outcome === "cancel") h.close();
      else for (const timer of timers.values()) timer.fn();
      await rejected;
      assert.ok(signals.every((signal) => signal.aborted));
      assert.equal(h.pending.size, 0);
      assert.equal(h.calls.filter((call) => call.options.method === "POST").length, 0);
      assert.equal(timers.size, 0);
    } finally {
      h.close();
    }
  }
});

test("selected run polling waits for initial history, spaces slow reads, and stops when hidden, left or terminal", async () => {
  for (const finish of ["terminal", "leave"]) {
    const timers = new Map();
    const doc = Object.assign(new EventTarget(), { visibilityState: "visible" });
    const history = [];
    const active = { items: [{ aggregate: { hasActiveExecutors: true } }] };
    const h = harness({
      timers,
      document: doc,
      transport(path, options) {
        if (!path.endsWith("/tasks/task_A/manual")) return;
        const waiting = Promise.withResolvers();
        history.push({ ...waiting, signal: options.signal });
        return waiting.promise;
      },
    });
    const tickFive = () => {
      for (const [id, timer] of [...timers])
        if (timer.ms === 5000) {
          timers.delete(id);
          timer.fn();
        }
    };
    try {
      await h.ready();
      assert.equal(history.length, 1);
      tickFive();
      tickFive();
      assert.equal(history.length, 1, "first history is still being read");
      history[0].resolve(Response.json(active));
      await h.ready();
      tickFive();
      await settle();
      assert.equal(history.length, 2);
      tickFive();
      tickFive();
      tickFive();
      assert.equal(history.length, 2, "no overlapping polls during a slow read");
      doc.visibilityState = "hidden";
      doc.dispatchEvent(new Event("visibilitychange"));
      await h.ready();
      assert.equal(history[1].signal.aborted, true);
      tickFive();
      tickFive();
      assert.equal(history.length, 2);
      doc.visibilityState = "visible";
      doc.dispatchEvent(new Event("visibilitychange"));
      tickFive();
      await settle();
      assert.equal(history.length, 3);
      history[1].resolve(Response.json({ items: [] }));
      await h.ready();
      assert.equal(
        h.render().manual.task_A.length,
        1,
        "hidden read must not overwrite current progress",
      );
      if (finish === "leave") {
        h.select(meta("task_B"));
        await h.ready();
        assert.equal(history[2].signal.aborted, true);
      }
      history[2].resolve(Response.json({ items: [] }));
      await h.ready();
      tickFive();
      tickFive();
      assert.equal(history.length, 3, "terminal and unselected tasks stop polling");
      if (finish === "terminal") assert.equal(h.render().manual.task_A.length, 0);
      else {
        h.select(meta("task_A", { taskVersion: 2 }));
        await h.ready();
        assert.equal(history.length, 4);
        tickFive();
        tickFive();
        assert.equal(
          history.length,
          4,
          "the previous visit's active run cannot start polling before fresh history arrives",
        );
        history[3].resolve(Response.json({ items: [] }));
        await h.ready();
        tickFive();
        assert.equal(history.length, 4);
      }
    } finally {
      h.close();
    }
  }
});

test("combined legacy evidence is checked against the original task and optional fallback reads stay local", async () => {
  const task = meta("task_A", { resourceBindings: [binding] });
  for (const mode of ["ready", "unavailable-legacy", "unavailable-provider", "foreign-authority"]) {
    const original = legacyAuthority(
      task,
      mode === "foreign-authority" ? { ownerSubject: "another_owner" } : {},
    );
    const selectedDetail = {
      metadata: task,
      scope: "owner_A:vault_A:1",
      vaultVersion: 1,
      current: () => true,
      read: async () => ({
        state: state(),
        legacy:
          mode === "unavailable-legacy"
            ? { status: "unavailable" }
            : { status: "ready", data: original },
        attribution:
          mode === "unavailable-legacy"
            ? null
            : mode === "unavailable-provider"
              ? { status: "unavailable" }
              : { status: "ready", data: connectionList },
        packet: null,
      }),
    };
    const h = harness({
      initial: task,
      selectedDetail,
      transport: (p) =>
        p.endsWith("/authority")
          ? Response.json(legacyAuthority(task))
          : p.endsWith("/persistent-connections")
            ? Response.json(connectionList)
            : undefined,
    });
    try {
      const m = await h.ready();
      assert.equal(m.executors.status, mode === "foreign-authority" ? "error" : "ready", mode);
      if (mode !== "foreign-authority")
        assert.deepEqual(Array.from(m.executors.providers), ["muse"]);
      assert.equal(countCalls(h, "/tasks/task_A"), 0);
      assert.equal(countCalls(h, "/authority"), mode === "unavailable-legacy" ? 1 : 0);
      assert.equal(
        countCalls(h, "/persistent-connections"),
        ["unavailable-legacy", "unavailable-provider"].includes(mode) ? 1 : 0,
      );
    } finally {
      h.close();
    }
  }
});

const retired = {
  ownerSubject: "subject_A",
  vaultId: "vault_A",
  taskId: "task_A",
  taskVersion: 1,
  executionEpoch: 1,
  definitionVersion: 4,
  lifecycleEpoch: 2,
  deletedAt: 10,
  status: "trashed",
};
const trashRow = {
  taskId: "task_A",
  title: "My task",
  canRestore: true,
  definition: retired,
  envelope: { metadata: { vaultId: "vault_A", taskId: "task_A", taskVersion: 1 } },
};
test("permanent deletion binds the reviewed task and its version before signing", async () => {
  let version = 5;
  const h = harness({
    transport: async (path) => {
      if (path.endsWith("/tasks/task_A"))
        return Response.json(
          state("task_A", { rules: { definition: { ...retired, definitionVersion: version } } }),
        );
      if (path.endsWith("/commands")) return Response.json({ accepted: true });
      if (path.endsWith("/maintenance"))
        return Response.json({ contractVersion: CONTRACT, complete: true, reviewRequired: false });
    },
  });
  const m = await h.ready();
  await assert.rejects(m.purgeTrashTask(trashRow, "foreign-scope"), /unlock_required/);
  await assert.rejects(m.purgeTrashTask(trashRow, m.scope), /version_conflict/);
  assert.equal(h.calls.filter((c) => c.path.endsWith("/commands")).length, 0);
  version = 4;
  assert.equal(await m.purgeTrashTask(trashRow, m.scope), "purgeComplete");
  assert.equal(h.calls.filter((c) => c.path.endsWith("/commands")).length, 1);
  assert.equal(h.calls.filter((c) => c.path.endsWith("/maintenance")).length, 1);
  h.close();
});
test("an erased original receipt is reconciled only by an authenticated maintenance outcome", async () => {
  for (const missing of [true, false]) {
    const pending = new Map([
      [
        "task_A",
        {
          taskId: "task_A",
          action: "purge",
          definition: retired,
          operationId: "original",
          body: {},
        },
      ],
    ]);
    const h = harness({
      pending,
      transport: async (path) => {
        if (path.endsWith("/commands")) return new Response(null, { status: 404 });
        if (path.endsWith("/maintenance"))
          return missing
            ? new Response(null, { status: 404 })
            : Response.json({ contractVersion: CONTRACT, complete: true, reviewRequired: false });
      },
    });
    h.workspace.clearConfirmedPurge = async (task, operation) => {
      assert.equal(operation, "original");
      pending.delete(task);
    };
    const m = await h.ready();
    if (missing) {
      await assert.rejects(m.purgeTrashTask(trashRow, m.scope), /purge_unconfirmed/);
      assert.equal(pending.size, 1);
    } else {
      assert.equal(await m.purgeTrashTask(trashRow, m.scope), "purgeComplete");
      assert.equal(pending.size, 0);
    }
    assert.equal(h.calls.filter((c) => c.path.endsWith("/commands")).length, 1);
    h.close();
  }
});
