const assert = require("node:assert/strict");
const test = require("node:test");
const {
  compile,
  contracts,
  catalogue,
  channels,
  stocks,
  response,
  settle,
  deferred,
} = require("./resource-library-helpers.cjs");
function harness({
  transport,
  active = true,
  configured = true,
  externalWatchlist = false,
  followsNeeded = true,
  online = true,
  resumeCatalogueOnNavigation = false,
} = {}) {
  let owner = "owner_A:1",
    workspaceScope = "vault_A:1",
    now = 100000,
    visible = true,
    index = 0,
    dirty = false,
    mounted = true,
    timer = 0;
  const cells = [],
    effects = [],
    calls = [],
    events = new Map(),
    timers = new Map();
  const changed = (before, after) =>
    !before || after.some((value, place) => value !== before[place]);
  const react = {
    useState(value) {
      const slot = index++;
      cells[slot] ??= { state: typeof value === "function" ? value() : value };
      return [
        cells[slot].state,
        (next) => {
          if (!mounted) return;
          const value = typeof next === "function" ? next(cells[slot].state) : next;
          dirty ||= value !== cells[slot].state;
          cells[slot].state = value;
        },
      ];
    },
    useRef(value) {
      const slot = index++;
      cells[slot] ??= { current: value };
      return cells[slot];
    },
    useCallback(value, deps) {
      const slot = index++;
      if (!cells[slot] || changed(cells[slot].deps, deps)) cells[slot] = { value, deps };
      return cells[slot].value;
    },
    useEffect(effect, deps) {
      const slot = index++;
      if (!cells[slot] || changed(cells[slot].deps, deps)) effects.push({ slot, effect, deps });
    },
  };
  const requestPrivate = async (service, route, key, options) => {
    const call = { service, route, key, options };
    calls.push(call);
    const custom = transport && (await transport(call));
    if (custom !== undefined) return custom;
    if (route === "/api/v2/resources/catalogue") return response(catalogue());
    if (route === "/api/v1/watchlist") return response(stocks());
    if (route === "/api/v1/channel-follows")
      return response(
        channels(
          key.startsWith("owner_A") ? "CREATOR_A" : "CREATOR_B",
          options.method === "PUT" ? options.json.expectedRevision + 1 : 1,
        ),
      );
    throw Error("Unexpected route");
  };
  const document = {
    get visibilityState() {
      return visible ? "visible" : "hidden";
    },
    addEventListener: (event, callback) => events.set(event, callback),
    removeEventListener: (event) => events.delete(event),
  };
  const window = {
    addEventListener: (event, callback) => events.set(event, callback),
    removeEventListener: (event) => events.delete(event),
    setTimeout(callback) {
      timers.set(++timer, callback);
      return timer;
    },
    clearTimeout: (id) => timers.delete(id),
  };
  const { useResourceLibrary } = compile(
    "../components/useResourceLibrary.ts",
    {
      react,
      "@/components/AuthProvider": {
        useAuth: () => ({
          status: owner ? "authenticated" : "anonymous",
          profile: owner ? { uid: owner } : null,
          sessionKey: owner,
          agentHubConfigured: configured,
          requestPrivate,
        }),
      },
      "@/lib/resource-library": contracts,
    },
    {
      document,
      window,
      navigator: {
        get onLine() {
          return online;
        },
      },
      Date: class extends Date {
        static now() {
          return now;
        }
      },
    },
  );
  const render = ({ flush = true } = {}) => {
    let result;
    do {
      index = 0;
      dirty = false;
      result = useResourceLibrary({
        active,
        externalWatchlist,
        workspaceScope,
        followsNeeded,
        resumeCatalogueOnNavigation,
      });
      if (flush)
        for (const entry of effects.splice(0)) {
          cells[entry.slot]?.cleanup?.();
          cells[entry.slot] = { deps: entry.deps, cleanup: entry.effect() };
        }
    } while (flush && dirty);
    if (!flush) effects.splice(0);
    return result;
  };
  return {
    render,
    calls,
    timers,
    owner: (next) => (owner = next),
    scope: (next) => (workspaceScope = next),
    advance: (ms) => (now += ms),
    capability: (next) => (configured = next),
    active: (next) => (active = next),
    followsNeeded: (next) => (followsNeeded = next),
    visibility(next) {
      visible = next;
      events.get("visibilitychange")?.();
    },
    connectivity(next) {
      online = next;
      events.get(next ? "online" : "offline")?.();
    },
    async ready() {
      render();
      await settle();
      return render();
    },
    unmount() {
      mounted = false;
      cells.forEach((cell) => cell.cleanup?.());
    },
  };
}

test("catalogue failure does not erase existing User lists or pretend they are empty", async () => {
  const h = harness({
    transport: ({ route }) => (route.includes("catalogue") ? response({}, 503) : undefined),
  });
  const view = await h.ready();
  assert.equal(view.catalogue.error, "unavailable");
  assert.equal(view.catalogue.data, null);
  assert.equal(view.watchlist.data.items[0].symbol, "SYNTH");
  assert.equal(view.follows.data.items[0].name, "CREATOR_A");
  h.unmount();
});

test("holdings demand leaves channels unknown while catalogue is ready, and entering channels starts its first read", async () => {
  const h = harness({ externalWatchlist: true, followsNeeded: false });
  try {
    const model = await h.ready();
    assert.ok(model.catalogue.data);
    assert.equal(model.catalogue.loading, false);
    assert.equal(model.follows.data, null);
    assert.equal(model.follows.loading, false);
    assert.equal(h.calls.filter((c) => c.route.endsWith("channel-follows")).length, 0);
    const catalogueReads = h.calls.filter((c) => c.route.includes("catalogue")).length;
    h.followsNeeded(true);
    const opening = h.render();
    assert.equal(opening.follows.loading, true);
    const loaded = await h.ready();
    assert.equal(loaded.follows.data.items[0].name, "CREATOR_A");
    assert.equal(h.calls.filter((c) => c.route.endsWith("channel-follows")).length, 1);
    assert.equal(
      h.calls.filter((c) => c.route.includes("catalogue")).length,
      catalogueReads,
      "Category demand does not restart catalogue",
    );
    h.followsNeeded(false);
    h.render();
    h.followsNeeded(true);
    await h.ready();
    assert.equal(h.calls.filter((c) => c.route.endsWith("channel-follows")).length, 1);
    h.followsNeeded(false);
    h.render();
    h.advance(30000);
    h.followsNeeded(true);
    await h.ready();
    assert.equal(h.calls.filter((c) => c.route.endsWith("channel-follows")).length, 2);
  } finally {
    h.unmount();
  }
});

test("changing channel demand does not cancel catalogue, and cancels only a hidden channel read", async () => {
  const discovery = deferred(),
    list = deferred();
  let hold = true;
  const h = harness({
    externalWatchlist: true,
    followsNeeded: false,
    transport: ({ route }) =>
      route.includes("catalogue")
        ? discovery.promise
        : hold && route.endsWith("channel-follows")
          ? list.promise
          : undefined,
  });
  try {
    h.render();
    const catalogueCall = h.calls[0];
    h.followsNeeded(true);
    h.render();
    await settle();
    assert.equal(catalogueCall.options.signal.aborted, false);
    const follows = h.calls.find((c) => c.route.endsWith("channel-follows"));
    assert.ok(follows);
    h.followsNeeded(false);
    h.render();
    assert.equal(follows.options.signal.aborted, true);
    assert.equal(catalogueCall.options.signal.aborted, false);
    discovery.resolve(response(catalogue()));
    list.resolve(response(channels("LATE")));
    await settle();
    assert.equal(h.render().follows.data, null);
    assert.equal(h.render().follows.loading, false);
    hold = false;
    h.followsNeeded(true);
    await h.ready();
    assert.equal(h.render().follows.data.items[0].name, "CREATOR_A");
  } finally {
    h.unmount();
  }
});

test("channel demand preserves failed-read unknown state and Owner/CAS fences without restarting an explicit write", async () => {
  const ack = deferred();
  let fail = true;
  const h = harness({
    followsNeeded: false,
    transport: ({ route, options }) =>
      options.method === "PUT"
        ? ack.promise
        : fail && route.endsWith("channel-follows")
          ? response({}, 503)
          : undefined,
  });
  try {
    await h.ready();
    h.followsNeeded(true);
    await h.ready();
    assert.equal(h.render().follows.data, null);
    assert.equal(h.render().follows.error, "unavailable");
    assert.equal(await h.render().saveFollows([]), false);
    fail = false;
    await h.render().reload("follows");
    const before = h.render();
    const write = before.saveFollows([]);
    await settle();
    const put = h.calls.find((c) => c.options.method === "PUT");
    assert.equal(put.options.json.expectedRevision, 1);
    h.followsNeeded(false);
    h.render();
    assert.equal(put.options.signal.aborted, false);
    ack.resolve(response(channels("SAVED", 2)));
    assert.equal(await write, true);
    await settle();
    assert.equal(h.calls.filter((c) => c.options.method === "PUT").length, 1);
    assert.equal(h.render().follows.data.revision, 2);
    h.owner("owner_B:2");
    assert.equal(h.render().follows.data, null);
    await h.ready();
    assert.equal(
      h.calls.filter((c) => c.key === "owner_B:2" && c.route.endsWith("channel-follows")).length,
      0,
    );
    h.followsNeeded(true);
    await h.ready();
    assert.equal(h.render().follows.data.items[0].name, "CREATOR_B");
    assert.equal(await before.saveFollows([]), false);
  } finally {
    h.unmount();
  }
});

test("User resource lists work without Portfolio or Hub and reuse fresh data when returning from Market", async () => {
  const h = harness({ configured: false });
  const view = await h.ready();
  assert.equal(view.catalogue.data, null);
  assert.equal(view.watchlist.data.items.length, 1);
  assert.ok(h.calls.every((call) => call.service === "user"));
  const count = h.calls.length;
  h.active(false);
  h.render();
  await settle();
  assert.equal(h.calls.length, count);
  h.active(true);
  await h.ready();
  assert.equal(h.calls.length, count);
  h.advance(30_000);
  h.active(false);
  h.render();
  h.active(true);
  await h.ready();
  assert.equal(h.calls.length, count + 2);
  h.unmount();
});

test("account switch masks rows during render and stale body, write and task callbacks cannot cross sessions", async () => {
  let block = false;
  const late = deferred();
  const h = harness({
    transport: ({ route, key }) =>
      block && key === "owner_A:1" && route.endsWith("watchlist") ? late.promise : undefined,
  });
  const before = await h.ready();
  const oldTask = before.useForTask;
  const oldSave = before.saveFollows;
  const oldItem = before.catalogue.data.groups[1].items[0];
  block = true;
  const load = before.reload("watchlist");
  await settle();
  h.owner("owner_B:1");
  const masked = h.render({ flush: false });
  assert.equal(masked.follows.data, null);
  assert.equal(masked.watchlist.data, null);
  let selected = 0;
  oldTask(oldItem, () => selected++);
  assert.equal(selected, 0);
  assert.equal(await oldSave([]), false);
  h.render();
  late.resolve(response(stocks("OLD")));
  await load;
  await settle();
  const after = h.render();
  assert.equal(after.follows.data.items[0].name, "CREATOR_B");
  assert.equal(after.watchlist.data.items[0].symbol, "SYNTH");
  h.owner(null);
  const logout = h.render({ flush: false });
  assert.equal(logout.follows.data, null);
  assert.equal(logout.catalogue.data, null);
  h.unmount();
});

test("follows replace uses current revision, normalizes locators and refreshes discovery only after success", async () => {
  const h = harness();
  const before = await h.ready();
  assert.equal(
    await before.saveFollows([{ name: "New", handleOrUrl: "@MiXeD", note: "note" }]),
    true,
  );
  const write = h.calls.find((call) => call.options.method === "PUT");
  assert.equal(write.key, "owner_A:1");
  assert.equal(write.options.json.expectedRevision, 1);
  assert.equal(write.options.json.items[0].handleOrUrl, "https://www.youtube.com/@mixed");
  await settle();
  const after = h.render();
  assert.equal(after.follows.data.revision, 2);
  assert.equal(h.calls.filter((call) => call.route.includes("catalogue")).length, 2);
  h.unmount();
});

test("CAS conflict and uncertain write forbid repeat writes until explicit successful reload", async () => {
  for (const mode of ["conflict", "malformed", "unavailable"]) {
    const h = harness({
      transport: ({ options }) =>
        options.method === "PUT"
          ? mode === "conflict"
            ? response({}, 409)
            : mode === "malformed"
              ? response({ invalid: true })
              : Promise.reject(Error("offline"))
          : undefined,
    });
    const before = await h.ready();
    assert.equal(await before.saveFollows([]), false);
    const after = h.render();
    assert.equal(after.follows.stale, true);
    assert.equal(after.follows.data.items[0].name, "CREATOR_A");
    assert.equal(await after.saveFollows([]), false);
    assert.equal(h.calls.filter((call) => call.options.method === "PUT").length, 1);
    await after.reload("follows");
    assert.equal(h.render().follows.stale, false);
    h.unmount();
  }
});

test("body read is fenced after account change and bounds streamed bytes rather than Content-Length", async () => {
  let controller;
  const readStarted = deferred();
  const h = harness({
    transport: ({ route, key }) =>
      route.endsWith("channel-follows") && key === "owner_A:1"
        ? new Response(
            new ReadableStream({
              start(value) {
                controller = value;
                readStarted.resolve();
              },
            }),
            { headers: { "Content-Type": "application/json", "Content-Length": "1" } },
          )
        : undefined,
  });
  h.render();
  await readStarted.promise;
  h.owner("owner_B:1");
  h.render({ flush: false });
  controller.enqueue(new TextEncoder().encode(JSON.stringify(channels("OLD_CREATOR"))));
  controller.close();
  h.render();
  await settle();
  assert.equal(h.render().follows.data.items[0].name, "CREATOR_B");
  h.unmount();
  const huge = harness({
    transport: ({ route }) =>
      route.endsWith("watchlist")
        ? new Response(" ".repeat(131073), {
            headers: { "Content-Type": "application/json", "Content-Length": "1" },
          })
        : undefined,
  });
  const failed = await huge.ready();
  assert.equal(failed.watchlist.error, "invalid_response");
  assert.equal(failed.watchlist.data, null);
  huge.unmount();
});

test("capability disable immediately masks catalogue and rejects stale task selection; User lists remain available", async () => {
  const h = harness();
  const before = await h.ready();
  let selected;
  before.useForTask(before.catalogue.data.groups[1].items[0], (value) => (selected = value));
  assert.deepEqual(Object.keys(selected).sort(), ["ref", "sourceEpoch"]);
  h.capability(false);
  const hidden = h.render({ flush: false });
  assert.equal(hidden.catalogue.data, null);
  selected = null;
  before.useForTask(before.catalogue.data.groups[1].items[0], (value) => (selected = value));
  assert.equal(selected, null);
  await h.ready();
  assert.equal(h.render().watchlist.data.items[0].symbol, "SYNTH");
  const calls = h.calls.length;
  h.capability(true);
  await h.ready();
  assert.equal(h.calls.length, calls + 1, "reenabling discovery must invalidate its old snapshot");
  h.unmount();
});

test("single-flight writes, revoked source epochs and aborted-body deadlines fail closed", async () => {
  const pending = deferred();
  const h = harness({
    transport: ({ options }) => (options.method === "PUT" ? pending.promise : undefined),
  });
  const before = await h.ready();
  const write = before.saveFollows([]);
  assert.equal(await before.saveFollows([]), false);
  assert.equal(h.calls.filter((call) => call.options.method === "PUT").length, 1);
  pending.resolve(response(channels("AFTER", 2)));
  assert.equal(await write, true);
  await settle();
  const now = h.render();
  const old = structuredClone(now.catalogue.data.groups[1].items[0]);
  old.sourceEpoch = 99;
  let selected = false;
  now.useForTask(old, () => (selected = true));
  assert.equal(selected, false);
  h.unmount();
  const timeout = harness({
    transport: ({ route }) =>
      route.endsWith("watchlist")
        ? new Response(new ReadableStream({ start() {} }), {
            headers: { "Content-Type": "application/json" },
          })
        : undefined,
  });
  timeout.render();
  await settle();
  for (const callback of [...timeout.timers.values()]) callback();
  await settle();
  const timedOut = timeout.render();
  assert.equal(timedOut.watchlist.error, "timeout");
  assert.equal(timedOut.watchlist.data, null);
  timeout.unmount();
});

test("creator GET permits server-added row metadata above the bounded write size", async () => {
  const items = Array.from({ length: 50 }, (_, i) => ({
    name: "Creator",
    handleOrUrl: `https://www.youtube.com/@creator_${i}`,
    note: "字".repeat(830),
  }));
  contracts.channelInputs(items);
  const rows = {
    revision: 1,
    limit: 50,
    items: items.map((item, i) => ({
      ...item,
      followId: `follow_${i}`,
      verification: "user_provided",
      addedAt: "2026-10-30T10:00:00Z",
    })),
  };
  assert.ok(new TextEncoder().encode(JSON.stringify(rows)).length > 131072);
  const h = harness({
    transport: ({ route }) => (route.endsWith("channel-follows") ? response(rows) : undefined),
  });
  const view = await h.ready();
  assert.equal(view.follows.error, "");
  assert.equal(view.follows.data.items.length, 50);
  h.unmount();
});

test("shared Market watchlist suppresses a second User list read without disabling creators or discovery", async () => {
  const h = harness({ externalWatchlist: true });
  const model = await h.ready();
  assert.equal(h.calls.filter((c) => c.route === "/api/v1/watchlist").length, 0);
  assert.ok(model.follows.data);
  assert.ok(model.catalogue.data);
  h.unmount();
});

test("an uninterrupted visit keeps verified resources actionable with no timer reads or preflight before a revision-guarded write", async () => {
  const h = harness();
  try {
    const original = await h.ready();
    const reads = h.calls.length;
    const item = original.catalogue.data.groups[1].items[0];
    for (const ms of [30_001, 120_000]) {
      h.advance(ms);
      const view = h.render();
      for (const source of ["catalogue", "watchlist", "follows"]) {
        assert.ok(view[source].data);
        assert.equal(view[source].stale, false);
        assert.equal(view[source].loading, false);
      }
      let selected;
      view.useForTask(item, (value) => (selected = value));
      assert.equal(selected.ref.resourceId, item.ref.resourceId);
      assert.equal(h.calls.length, reads);
      assert.equal(h.timers.size, 0);
    }
    assert.equal(await h.render().saveFollows([]), true);
    assert.equal(h.calls[reads].options.method, "PUT");
    assert.equal(h.calls[reads].options.json.expectedRevision, original.follows.data.revision);
  } finally {
    h.unmount();
  }
});

test("an offline event retains rows and blocks mutations; reconnection verifies only demanded sources once", async () => {
  const h = harness({ externalWatchlist: true });
  try {
    const before = await h.ready();
    const item = before.catalogue.data.groups[1].items[0];
    const reads = h.calls.length;
    h.connectivity(false);
    const offline = h.render();
    assert.equal(offline.follows.data.items[0].name, "CREATOR_A");
    assert.equal(offline.follows.stale, true);
    assert.equal(offline.catalogue.stale, true);
    let selected = false;
    before.useForTask(item, () => (selected = true));
    assert.equal(selected, false);
    assert.equal(await before.saveFollows([]), false);
    await offline.reload("catalogue");
    assert.equal(h.calls.length, reads);
    h.followsNeeded(false);
    h.render();
    h.connectivity(true);
    const recovered = await h.ready();
    assert.equal(h.calls.length, reads + 1);
    assert.equal(h.calls.at(-1).route, "/api/v2/resources/catalogue");
    assert.equal(recovered.catalogue.stale, false);
    assert.equal(recovered.follows.stale, true);
    recovered.useForTask(item, () => (selected = true));
    assert.equal(selected, true);
    h.followsNeeded(true);
    assert.equal((await h.ready()).follows.stale, false);
    assert.equal(h.calls.length, reads + 2);
  } finally {
    h.unmount();
  }
});

test("a fresh return to Resources keeps completed catalogue and channel rows", async () => {
  const h = harness();
  try {
    const original = await h.ready();
    const reads = h.calls.length;
    assert.ok(original.catalogue.data);
    assert.ok(original.follows.data);
    h.visibility(false);
    h.render();
    h.advance(29 * 60 * 1000);
    h.visibility(true);
    const resumed = await h.ready();
    assert.deepEqual(resumed.catalogue.data, original.catalogue.data);
    assert.deepEqual(resumed.follows.data, original.follows.data);
    assert.equal(h.calls.length, reads);
  } finally {
    h.unmount();
  }
});

test("opening while offline reports unavailability, then defers recovery until the page is visible", async () => {
  const h = harness({ online: false, externalWatchlist: true, followsNeeded: false });
  try {
    const offline = await h.ready();
    assert.equal(offline.catalogue.error, "unavailable");
    assert.equal(offline.catalogue.loading, false);
    assert.equal(h.calls.length, 0);
    h.visibility(false);
    h.render();
    h.connectivity(true);
    await h.ready();
    assert.equal(h.calls.length, 0);
    h.visibility(true);
    assert.ok((await h.ready()).catalogue.data);
    assert.equal(h.calls.length, 1);
  } finally {
    h.unmount();
  }
});

test("expired refresh retains successful resources with explicit stale state and blocks stale actions until recovery", async () => {
  let fail = false;
  const h = harness({ transport: () => (fail ? response({}, 503) : undefined) });
  const before = await h.ready();
  const item = before.catalogue.data.groups[1].items[0];
  h.active(false);
  h.render();
  h.advance(30_000);
  fail = true;
  h.active(true);
  const refreshing = h.render();
  assert.equal(refreshing.catalogue.loading, true);
  assert.equal(refreshing.catalogue.stale, false);
  assert.equal(refreshing.catalogue.data.groups[1].items[0].ref.resourceId, item.ref.resourceId);
  let selected = 0;
  before.useForTask(item, () => selected++);
  assert.equal(selected, 0);
  await settle();
  const failed = h.render();
  assert.equal(failed.catalogue.error, "unavailable");
  assert.equal(failed.catalogue.stale, true);
  assert.equal(failed.watchlist.data.items[0].symbol, "SYNTH");
  assert.equal(failed.follows.data.items[0].name, "CREATOR_A");
  assert.equal(await failed.saveFollows([]), false);
  fail = false;
  await failed.reload("catalogue");
  await failed.reload("follows");
  const recovered = h.render();
  assert.equal(recovered.catalogue.stale, false);
  recovered.useForTask(item, () => selected++);
  assert.equal(selected, 1);
  assert.equal(await recovered.saveFollows([]), true);
  h.unmount();
});

test("vault generation masks resource snapshots and fences old read, write and selection callbacks before effects", async () => {
  let block = false;
  const late = deferred();
  const h = harness({
    transport: ({ route }) => (block && route.includes("catalogue") ? late.promise : undefined),
  });
  const before = await h.ready();
  block = true;
  const read = before.reload("catalogue");
  h.scope("vault_A:2");
  const masked = h.render({ flush: false });
  assert.equal(masked.catalogue.data, null);
  assert.equal(masked.follows.data, null);
  let selected = 0;
  before.useForTask(before.catalogue.data.groups[1].items[0], () => selected++);
  assert.equal(selected, 0);
  assert.equal(await before.saveFollows([]), false);
  block = false;
  h.render();
  late.resolve(response(catalogue()));
  await read;
  await settle();
  assert.ok(h.render().catalogue.data);
  assert.equal(h.calls.filter((c) => c.route.endsWith("channel-follows")).length, 2);
  h.unmount();
});

test("rapid navigation cancels a refresh, keeps the prior snapshot and rejects its late body", async () => {
  let block = false;
  const late = deferred();
  const h = harness({
    transport: ({ route }) => (block && route.endsWith("watchlist") ? late.promise : undefined),
  });
  const before = await h.ready();
  block = true;
  const read = before.reload("watchlist");
  await settle();
  const old = h.calls.at(-1);
  h.active(false);
  h.render();
  assert.equal(old.options.signal.aborted, true);
  assert.equal(h.render().watchlist.data.items[0].symbol, "SYNTH");
  block = false;
  h.active(true);
  await h.ready();
  late.resolve(response(stocks("LATE")));
  await read;
  await settle();
  assert.equal(h.render().watchlist.data.items[0].symbol, "SYNTH");
  assert.equal(h.render().watchlist.stale, false);
  h.unmount();
});

test("rapid same-document navigation reuses one demand-started catalogue read", async () => {
  const first = deferred();
  const h = harness({
    externalWatchlist: true,
    followsNeeded: false,
    resumeCatalogueOnNavigation: true,
    transport: ({ route }) => (route.endsWith("/catalogue") ? first.promise : undefined),
  });
  try {
    h.render();
    await settle();
    const read = h.calls[0];
    assert.ok(read.route.endsWith("/catalogue"));
    for (let index = 0; index < 3; index++) {
      h.active(false);
      h.render();
      h.active(true);
      h.render();
    }
    assert.equal(read.options.signal.aborted, false);
    assert.equal(h.calls.length, 1);
    first.resolve(response(catalogue()));
    assert.ok((await h.ready()).catalogue.data);
    h.active(false);
    h.render();
    h.active(true);
    assert.ok((await h.ready()).catalogue.data);
    assert.equal(h.calls.length, 1);
    await h.render().reload("catalogue");
    assert.equal(h.calls.length, 2, "an explicit refresh still contacts the server");
  } finally {
    h.unmount();
  }
});

test("a catalogue read kept across routes still cancels when the document is hidden", async () => {
  const first = deferred();
  let delayed = true;
  const h = harness({
    externalWatchlist: true,
    followsNeeded: false,
    resumeCatalogueOnNavigation: true,
    transport: ({ route }) => (delayed && route.endsWith("/catalogue") ? first.promise : undefined),
  });
  try {
    h.render();
    await settle();
    h.active(false);
    h.render();
    h.visibility(false);
    h.render();
    assert.equal(h.calls[0].options.signal.aborted, true);
    first.resolve(response(catalogue()));
    assert.equal((await h.ready()).catalogue.data, null);
    delayed = false;
    h.visibility(true);
    await h.ready();
    assert.equal(h.calls.length, 1);
    h.active(true);
    assert.ok((await h.ready()).catalogue.data);
    assert.equal(h.calls.length, 2);
  } finally {
    h.unmount();
  }
});

test("a follows write invalidates cached discovery immediately, and uncertain navigation never repeats the write", async () => {
  const ack = deferred();
  const h = harness({
    transport: ({ options }) => (options.method === "PUT" ? ack.promise : undefined),
  });
  const before = await h.ready();
  const write = before.saveFollows([]);
  const during = h.render();
  assert.equal(during.catalogue.stale, true);
  let selected = 0;
  during.useForTask(before.catalogue.data.groups[1].items[0], () => selected++);
  assert.equal(selected, 0);
  h.active(false);
  h.render();
  await write;
  assert.equal(h.render().follows.stale, true);
  assert.equal(h.render().writeError, "reload_required");
  ack.resolve(response(channels("LATE", 2)));
  h.active(true);
  await h.ready();
  assert.equal(h.render().follows.stale, false);
  assert.equal(h.calls.filter((c) => c.options.method === "PUT").length, 1);
  h.unmount();
});
