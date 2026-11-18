const assert = require("node:assert/strict");
const test = require("node:test");
const { compile } = require("./resource-library-helpers.cjs");

function workspace() {
  let now = 100;
  let nextId = 0;
  const frames = new Map();
  const measurements = [];
  const states = { tasks: "loading", agents: "loading" };
  const location = new URL("https://example.test/tasks");
  const document = new EventTarget();
  document.visibilityState = "visible";
  document.getElementById = () => ({});
  document.querySelector = (selector) => {
    const view = selector.includes("task-center-title")
      ? "tasks"
      : selector.includes("agent-connections")
        ? "agents"
        : null;
    if (!view) return null;
    return {
      getAttribute: (name) =>
        ({
          "data-load-state": states[view],
          "data-load-scope": view === "tasks" ? "task-list" : "agent-connections",
        })[name] ?? null,
    };
  };
  const performance = {
    now: () => now,
    clearMeasures() {},
    measure(name, options) {
      const measurement = { name, ...options };
      measurements.push(measurement);
      return measurement;
    },
  };
  const window = Object.assign(new EventTarget(), {
    document,
    location,
    performance,
    requestAnimationFrame(callback) {
      frames.set(++nextId, callback);
      return nextId;
    },
    cancelAnimationFrame: (id) => frames.delete(id),
    setTimeout: () => ++nextId,
    clearTimeout() {},
  });
  const { createWorkspaceJourneyTracker } = compile(
    "../components/useWorkspaceJourney.ts",
    {
      react: require("react"),
      "@/lib/inbox-link": compile("../lib/inbox-link.ts", {}, { URLSearchParams }),
      "@/lib/workspace-routes": compile("../lib/workspace-routes.ts"),
    },
    {
      window,
      document,
      performance,
      location,
      MutationObserver: class {
        observe() {}
        disconnect() {}
      },
    },
  );
  const tracker = createWorkspaceJourneyTracker();
  return {
    tracker,
    window,
    states,
    location,
    measurements,
    update(view = "tasks", access = "available") {
      tracker.update({ view, access, owner: "PRIVATE_FIXTURE_OWNER", marketState: "loading" });
    },
    advance(ms) {
      now += ms;
    },
    paint() {
      for (let frame = 0; frame < 3; frame++) {
        now += 16;
        const pending = [...frames.values()];
        frames.clear();
        for (const callback of pending) callback(now);
      }
    },
  };
}

test("a ready list emits one bounded User Timing detail across rerenders", () => {
  const h = workspace();
  h.states.tasks = "ready";
  h.update();
  h.paint();
  h.update();
  h.paint();
  h.tracker.dispose();
  assert.equal(h.measurements.length, 1);
  const [measurement] = h.measurements;
  assert.equal(measurement.name, "foliocrew.workspace.journey");
  assert.deepEqual(
    { ...measurement.detail },
    { journey: "tasks", outcome: "ready", entry: "document" },
  );
  assert.doesNotMatch(JSON.stringify(measurement), /PRIVATE_FIXTURE_OWNER/);
});

test("replacing a pending task navigation starts an independent Agent observation", () => {
  const h = workspace();
  h.states.tasks = "ready";
  h.update();
  h.tracker.navigate("agents");
  h.location.pathname = "/agents";
  h.states.agents = "ready";
  h.update("agents");
  h.paint();
  h.tracker.dispose();
  assert.deepEqual(
    h.measurements.map((m) => [m.detail.journey, m.detail.outcome, m.detail.entry]),
    [
      ["tasks", "interrupted", "document"],
      ["agents", "ready", "navigation"],
    ],
  );
});

test("unlock starts a separate timer after time spent waiting for the user", () => {
  const h = workspace();
  h.update("tasks", "blocked");
  h.paint();
  h.advance(20_000);
  h.states.tasks = "ready";
  h.update("tasks", "available");
  h.paint();
  h.tracker.dispose();
  assert.deepEqual(
    h.measurements.map((m) => [m.detail.outcome, m.detail.entry]),
    [
      ["access_required", "document"],
      ["ready", "after_unlock"],
    ],
  );
  assert.ok(h.measurements[1].start >= 20_000);
});

for (const transition of ["transitionend", "transitioncancel"]) {
  test(`a covered Market quote becomes usable after the mobile drawer's ${transition}`, () => {
    const h = workspace();
    const { document } = h.window;
    h.window.innerWidth = 375;
    h.window.innerHeight = 812;
    const quote = {
      getBoundingClientRect: () => ({ x: 25, y: 120, width: 80, height: 24 }),
      contains: (element) => element === quote,
    };
    const drawer = {};
    let foreground = drawer;
    document.querySelectorAll = () => [quote];
    document.elementFromPoint = () => foreground;
    h.tracker.update({ view: "markets", access: "available", owner: null, marketState: "ready" });
    h.paint();
    assert.equal(h.measurements.length, 0);

    // Only the CSS transition changes the hit target. React and the DOM observer remain idle.
    foreground = quote;
    h.paint();
    assert.equal(h.measurements.length, 0);
    document.dispatchEvent(new Event(transition));
    h.paint();
    assert.equal(h.measurements.length, 1);
    assert.deepEqual(
      { ...h.measurements[0].detail },
      {
        journey: "market",
        entry: "document",
        outcome: "ready",
      },
    );
    assert.ok(h.measurements[0].end < 15_000);
    h.tracker.dispose();
  });
}
