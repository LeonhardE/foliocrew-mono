const test = require("node:test"),
  assert = require("node:assert/strict");
const React = require("react"),
  jsx = require("react/jsx-runtime");
const { compile, deferred, settle } = require("./resource-library-helpers.cjs");
const { hooks, all } = require("./resource-ui-harness.cjs");

function modules(timers = new Map()) {
  return {
    timers,
    api: compile(
      "../components/WorkspacePanels.tsx",
      {
        react: React,
        "react/jsx-runtime": jsx,
        "next-intl": { useTranslations: () => (v) => v },
        "./WorkspaceFeedback": { InlineError: () => null, LoadingIndicator: () => null },
      },
      {
        setTimeout(fn, ms) {
          const key = {};
          timers.set(key, { fn, ms });
          return key;
        },
        clearTimeout(key) {
          timers.delete(key);
        },
      },
    ),
  };
}
test("module loading has an in-place failure deadline and a fresh explicit retry", async () => {
  const { api, timers } = modules(),
    old = deferred();
  const first = api.loadWorkspaceModule(() => old.promise);
  const rejected = assert.rejects(first, /module_unavailable/);
  assert.equal(timers.size, 1);
  [...timers.values()][0].fn();
  await rejected;
  old.resolve("late chunk");
  await settle();
  assert.equal(timers.size, 0);
  assert.equal(await api.loadWorkspaceModule(async () => "fresh chunk"), "fresh chunk");
  assert.equal(timers.size, 0);
});
test("module boundary replaces a failed page with local recovery without replacing its workspace parent", () => {
  const { api } = modules();
  const parentSession = {},
    props = { children: { parentSession }, fallback: "retry-local-module" };
  const boundary = new api.WorkspaceModuleBoundary(props);
  assert.equal(boundary.render().parentSession, parentSession);
  boundary.state = api.WorkspaceModuleBoundary.getDerivedStateFromError(Error("chunk failed"));
  assert.equal(boundary.render(), "retry-local-module");
  const retried = new api.WorkspaceModuleBoundary(props);
  assert.equal(retried.render().parentSession, parentSession);
});
function configuration() {
  const h = hooks(),
    requests = [],
    timers = new Map(),
    events = new Map();
  let now = 100000,
    active = true,
    visible = true;
  const destination = {
    schemaVersion: 1,
    enabled: true,
    hubOrigin: "https://agent-hub-api-123456789.northamerica-northeast2.run.app",
  };
  const connection = compile("../lib/agent-connections.ts", {
    "./task-types": compile("../lib/task-types.ts"),
  });
  const link = compile("../lib/agent-link.ts", { "./agent-connections": connection });
  const { useAgentLinkConfiguration } = compile(
    "../components/useAgentLinkConfiguration.ts",
    { react: h.react, "@/lib/agent-link": link },
    {
      Date: class extends Date {
        static now() {
          return now;
        }
      },
      document: {
        get visibilityState() {
          return visible ? "visible" : "hidden";
        },
        addEventListener(k, v) {
          events.set(k, v);
        },
        removeEventListener(k) {
          events.delete(k);
        },
      },
      window: {
        setTimeout(fn, ms) {
          const key = {};
          timers.set(key, { fn, ms });
          return key;
        },
        clearTimeout(key) {
          timers.delete(key);
        },
      },
      fetch: async (_url, options) => {
        const request = deferred();
        requests.push({ ...request, options });
        return request.promise;
      },
    },
  );
  return {
    requests,
    timers,
    destination,
    render: () => h.render(() => useAgentLinkConfiguration(active)),
    active(v) {
      active = v;
    },
    advance(ms) {
      now += ms;
    },
    hidden(v) {
      visible = !v;
      events.get("visibilitychange")?.();
    },
    close: () => h.close(),
  };
}
test("route reentry reuses public Agent destination metadata and refresh failure keeps the valid origin", async () => {
  const h = configuration();
  h.render();
  assert.equal(h.requests.length, 1);
  h.requests[0].resolve(Response.json(h.destination));
  await settle();
  assert.equal(h.render().data.hubOrigin, h.destination.hubOrigin);
  h.active(false);
  h.render();
  h.active(true);
  h.render();
  assert.equal(h.requests.length, 1);
  h.advance(60001);
  h.active(false);
  h.render();
  h.active(true);
  h.render();
  assert.equal(h.requests.length, 2);
  h.requests[1].resolve(Response.json({}, { status: 503 }));
  await settle();
  const state = h.render();
  assert.equal(state.error, true);
  assert.equal(state.data.hubOrigin, h.destination.hubOrigin);
  h.close();
});
test("public Agent config deadline and hidden late reply cannot create an unverified destination", async () => {
  const h = configuration();
  h.render();
  [...h.timers.values()][0].fn();
  await settle();
  assert.equal(h.render().error, true);
  assert.equal(h.render().data, null);
  h.hidden(true);
  h.render();
  h.requests[0].resolve(Response.json(h.destination));
  await settle();
  assert.equal(h.render().data, null);
  h.close();
});

// Actual component code and React elements; deterministic lifecycle only for the DOM-free host.
function taskModuleHost(load, locale) {
  const { readFileSync } = require("node:fs"),
    path = require("node:path"),
    vm = require("node:vm");
  const { transformSync } = require("next/dist/build/swc");
  let activeHooks,
    child = hooks(),
    childKey,
    writes = 0,
    imports = 0,
    reloads = 0,
    last;
  let panel = hooks();
  const timers = new Map();
  const source = readFileSync(path.join(__dirname, "../components/WorkspacePanels.tsx"), "utf8");
  assert.equal(source.split('import("./TasksPanel").then').length, 2);
  // Replace only the code-chunk transport; production loader/component behavior is unchanged.
  const { code } = transformSync(
    source.replace('import("./TasksPanel").then', "__taskImport().then"),
    {
      filename: "WorkspacePanels.tsx",
      jsc: {
        parser: { syntax: "typescript", tsx: true },
        target: "es2022",
        transform: { react: { runtime: "automatic" } },
      },
      module: { type: "commonjs" },
    },
  );
  const r = {
    ...React,
    useState(value) {
      const [state, set] = activeHooks.react.useState(value);
      return [
        state,
        (next) => {
          writes++;
          set(next);
        },
      ];
    },
    useEffect: (...args) => activeHooks.react.useEffect(...args),
    useMemo(fn, deps) {
      const ref = activeHooks.react.useRef();
      if (!ref.current || deps.some((v, i) => ref.current.deps[i] !== v))
        ref.current = { value: fn(), deps };
      return ref.current.value;
    },
  };
  const Loading = () => null,
    ErrorView = require("./workspace-feedback-helpers.cjs").component(
      "./WorkspaceFeedback",
    ).InlineError;
  const translate = locale
    ? require("next-intl").createTranslator({
        locale,
        messages: require(`../messages/${locale}.json`),
        namespace: "workspaceFeedback",
      })
    : (key) => key;
  const location = {
    reload() {
      assert.equal(this, location, "use the native location receiver");
      reloads++;
    },
  };
  const provided = {
    react: r,
    "react/jsx-runtime": jsx,
    "next-intl": { useTranslations: () => translate },
    "./WorkspaceFeedback": { InlineError: ErrorView, LoadingIndicator: Loading },
  };
  const module = { exports: {} };
  vm.runInNewContext(code, {
    module,
    exports: module.exports,
    require: (name) => {
      assert.ok(name in provided, name);
      return provided[name];
    },
    window: { location },
    fetch() {
      assert.fail("module recovery must not issue business or public probes");
    },
    __taskImport: () => {
      imports++;
      return load();
    },
    setTimeout(fn, ms) {
      const id = {};
      timers.set(id, { fn, ms });
      return id;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
  });
  function draw(props = {}, name = "TasksPanel") {
    activeHooks = panel;
    const entry = module.exports[name](props);
    const boundary = panel.render(() => entry.type(entry.props));
    const suspense = boundary.props.children,
      loader = suspense.props.children;
    if (boundary.key !== childKey) {
      child.close();
      child = hooks();
      childKey = boundary.key;
    }
    activeHooks = child;
    assert.equal(
      typeof loader.type,
      "function",
      "Tasks must use an effect loader rather than first-render React.lazy suspension",
    );
    const body = child.render(() => loader.type(loader.props));
    return (last = { boundary, suspense, loader, body });
  }
  return {
    draw,
    api: module.exports,
    timers,
    Loading,
    imports: () => imports,
    writes: () => writes,
    reloads: () => reloads,
    error: () => all(last.boundary.props.fallback, (node) => node.type === ErrorView)[0],
    retry: () =>
      all(last.boundary.props.fallback, (node) => node.type === ErrorView)[0].props.onRetry(),
    describe(name, props = {}) {
      activeHooks = panel;
      const entry = module.exports[name](props);
      return panel.render(() => entry.type(entry.props));
    },
    remount() {
      child.close();
      panel.close();
      child = hooks();
      panel = hooks();
      childKey = undefined;
      last = null;
    },
    close: () => {
      child.close();
      panel.close();
    },
  };
}

test("Tasks load on mount through ordinary state and render resolved code with current props", async () => {
  const gate = deferred();
  let mounts = 0;
  function Task(props) {
    const [owner] = React.useState(props.owner);
    mounts++;
    return React.createElement("p", null, owner);
  }
  const h = taskModuleHost(() => gate.promise);
  try {
    assert.equal(h.imports(), 0);
    let x = h.draw({ owner: "OWNER_A" });
    assert.equal(h.imports(), 1);
    assert.equal(mounts, 0);
    assert.equal(x.body.props.style.minBlockSize, 180);
    assert.equal(x.body.props.children.type, h.Loading);
    assert.equal(x.body.props.children.props.busy, true);
    h.draw({ owner: "OWNER_B" });
    gate.resolve({ default: Task });
    await settle();
    x = h.draw({ owner: "OWNER_B" });
    assert.equal(x.body.type, Task);
    assert.equal(h.imports(), 1);
    assert.equal(mounts, 0, "loading code must not mount Task hooks");
    const html = require("react-dom/server").renderToStaticMarkup(x.body);
    assert.ok(html.includes("OWNER_B"));
    assert.ok(!html.includes("OWNER_A"));
    assert.equal(mounts, 1, "resolved element renders with the actual React renderer");
  } finally {
    h.close();
  }
});

test("Task module rejection renders the fixed boundary error and retry remounts in place", async () => {
  let rejectFirst;
  const first = {
      promise: new Promise((_, reject) => {
        rejectFirst = reject;
      }),
    },
    second = deferred();
  let calls = 0;
  const h = taskModuleHost(() => (++calls === 1 ? first.promise : second.promise));
  const Task = () => null;
  try {
    const initial = h.draw({ session: "SAME_SESSION" });
    rejectFirst(Error("RAW_CHUNK_FAILURE_SENTINEL"));
    await settle();
    assert.throws(
      () => h.draw({ session: "SAME_SESSION" }),
      (e) => e.message === "module_unavailable",
    );
    const boundary = new h.api.WorkspaceModuleBoundary(initial.boundary.props);
    boundary.state = h.api.WorkspaceModuleBoundary.getDerivedStateFromError(
      Error("module_unavailable"),
    );
    assert.equal(boundary.render(), initial.boundary.props.fallback);
    assert.equal(h.error().props.message, "moduleUnavailable");
    h.retry();
    const retry = h.draw({ session: "SAME_SESSION" });
    assert.notEqual(retry.boundary.key, initial.boundary.key);
    assert.equal(h.imports(), 2);
    second.resolve({ default: Task });
    await settle();
    const ready = h.draw({ session: "SAME_SESSION" });
    assert.equal(ready.body.type, Task);
    assert.equal(ready.body.props.session, "SAME_SESSION");
    assert.equal(h.timers.size, 0);
  } finally {
    h.close();
  }
});

test("Task module keeps the original15s deadline and late timed-out code cannot replace a retry", async () => {
  const first = deferred(),
    second = deferred();
  let calls = 0;
  const h = taskModuleHost(() => (++calls === 1 ? first.promise : second.promise));
  const Old = () => null,
    Current = () => null;
  try {
    h.draw();
    assert.equal(h.timers.size, 1);
    assert.equal([...h.timers.values()][0].ms, 15000);
    [...h.timers.values()][0].fn();
    await settle();
    assert.throws(
      () => h.draw(),
      (e) => e.message === "module_unavailable",
    );
    h.retry();
    h.draw();
    second.resolve({ default: Current });
    await settle();
    assert.equal(h.draw().body.type, Current);
    const writes = h.writes();
    first.resolve({ default: Old });
    await settle();
    assert.equal(h.draw().body.type, Current);
    assert.equal(h.writes(), writes);
    assert.equal(h.imports(), 2);
    assert.equal(h.timers.size, 0);
  } finally {
    h.close();
  }
});

test("Task code sharing never retains an old mount or Owner props across unmount and remount", async () => {
  for (const remountPending of [false, true]) {
    const gate = deferred(),
      h = taskModuleHost(() => gate.promise);
    const Task = (props) => React.createElement("p", null, props.owner);
    try {
      h.draw({ owner: "OLD_OWNER" });
      const writes = h.writes();
      h.close();
      if (remountPending) {
        h.remount();
        h.draw({ owner: "NEW_OWNER" });
      }
      gate.resolve({ default: Task });
      await settle();
      assert.equal(
        h.writes() - writes,
        remountPending ? 1 : 0,
        "an old effect must not schedule state after unmount",
      );
      if (!remountPending) h.remount();
      const x = h.draw({ owner: "NEW_OWNER" });
      assert.equal(x.body.type, Task);
      assert.equal(h.imports(), 1, "share only the code promise/success, not another import");
      const html = require("react-dom/server").renderToStaticMarkup(x.body);
      assert.ok(html.includes("NEW_OWNER"));
      assert.ok(!html.includes("OLD_OWNER"));
    } finally {
      h.close();
    }
  }
});

test("a resolved Task component keeps the original real Suspense boundary for its children", async () => {
  const suspended = deferred();
  let mounts = 0;
  function Task() {
    mounts++;
    throw suspended.promise;
  }
  const h = taskModuleHost(async () => ({ default: Task }));
  try {
    h.draw();
    await settle();
    const x = h.draw();
    assert.equal(x.body.type, Task);
    assert.equal(x.suspense.type, React.Suspense);
    const fallback = React.createElement("span", null, "GENUINE_CHILD_FALLBACK");
    assert.equal(mounts, 0, "code loading alone does not render the suspending Task");
    const html = require("react-dom/server").renderToString(
      React.cloneElement(x.suspense, { fallback }, x.body),
    );
    assert.ok(html.includes("GENUINE_CHILD_FALLBACK"));
    assert.ok(mounts > 0);
  } finally {
    suspended.resolve();
    h.close();
  }
});

test("other workspace panels retain lazy loading and do not start a Task import", () => {
  const h = taskModuleHost(() => {
    throw Error("Task must not preload");
  });
  try {
    for (const name of [
      "SettingsPanel",
      "ResourcesPanel",
      "PersistentAgentsPanel",
      "CandlestickChart",
    ]) {
      const boundary = h.describe(name),
        suspense = boundary.props.children;
      assert.equal(suspense.type, React.Suspense);
      assert.equal(typeof suspense.props.children.type, "object", name);
    }
    assert.equal(h.imports(), 0);
  } finally {
    h.close();
  }
});

test("a fulfilled Task module without a default component fails closed to the same retry", async () => {
  const Task = () => null;
  let reads = 0;
  const h = taskModuleHost(async () => (++reads === 1 ? {} : { default: Task }));
  try {
    h.draw();
    await settle();
    assert.throws(
      () => h.draw(),
      (e) => e.message === "module_unavailable",
    );
    h.retry();
    h.draw();
    await settle();
    assert.equal(h.draw().body.type, Task);
    assert.equal(h.imports(), 2);
  } finally {
    h.close();
  }
});

test("failed modules offer localized retry and page reload only after explicit user activation", async () => {
  const { renderToStaticMarkup } = require("react-dom/server");
  for (const locale of ["en", "zh", "zh-Hant"]) {
    const messages = require(`../messages/${locale}.json`).workspaceFeedback;
    const h = taskModuleHost(async () => {
      throw Error("RAW_FAILURE_SENTINEL");
    }, locale);
    try {
      const initial = h.draw({ session: "PRESERVED_SESSION" });
      assert.equal(h.reloads(), 0);
      await settle();
      assert.throws(
        () => h.draw(),
        (error) => error.message === "module_unavailable",
      );
      const boundary = new h.api.WorkspaceModuleBoundary(initial.boundary.props);
      assert.equal(boundary.render(), initial.boundary.props.children);
      boundary.state = h.api.WorkspaceModuleBoundary.getDerivedStateFromError(Error("unknown"));
      const recovery = boundary.render();
      const html = renderToStaticMarkup(recovery);
      assert.equal((html.match(/<button /g) || []).length, 2, locale);
      assert.ok(html.includes(messages.moduleUnavailable), locale);
      assert.ok(html.includes(messages.retry), locale);
      assert.ok(html.includes(messages.reloadPage), locale);
      assert.ok(html.includes(messages.moduleReloadHelp), locale);
      assert.ok(!html.includes("RAW_FAILURE_SENTINEL"));
      assert.equal(h.imports(), 1);
      assert.equal(h.timers.size, 0);
      assert.equal(h.reloads(), 0, "failure and rendering must not navigate");
      const reload = all(recovery, (node) => node.type === "button")[0];
      assert.equal(reload.props.type, "button");
      reload.props.onClick();
      assert.equal(h.reloads(), 1, "only a deliberate click invokes normal location.reload");
      assert.equal(h.imports(), 1, "page reload must not create an in-place module retry or probe");
    } finally {
      h.close();
    }
  }
});

test("the original module deadline keeps both recovery choices local until the user reloads", async () => {
  const gate = deferred();
  const h = taskModuleHost(() => gate.promise);
  try {
    const initial = h.draw({ session: "UNCHANGED_SESSION" });
    assert.equal([...h.timers.values()][0].ms, 15000);
    assert.equal(h.reloads(), 0);
    [...h.timers.values()][0].fn();
    await settle();
    assert.throws(
      () => h.draw(),
      (error) => error.message === "module_unavailable",
    );
    const fallback = initial.boundary.props.fallback;
    assert.equal(all(fallback, (node) => node.type === "button").length, 1);
    assert.equal(h.reloads(), 0, "the deadline must never reload an unlocked document");
    h.retry();
    const retried = h.draw({ session: "UNCHANGED_SESSION" });
    assert.notEqual(retried.boundary.key, initial.boundary.key);
    assert.equal(retried.loader.props.session, "UNCHANGED_SESSION");
    assert.equal(h.imports(), 2);
    assert.equal(h.reloads(), 0, "the original retry remains in place");
  } finally {
    gate.resolve({ default: () => null });
    await settle();
    h.close();
  }
});
