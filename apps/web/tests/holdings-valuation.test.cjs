const test = require("node:test"),
  assert = require("node:assert/strict");
const path = require("node:path"),
  { pathToFileURL } = require("node:url");
const { compile } = require("./resource-library-helpers.cjs");
const { hooks, jsx, all } = require("./resource-ui-harness.cjs");
const copy = (v) => structuredClone(v),
  at = "2026-11-14T06:00:00Z",
  day = "2026-11-13";
const factsApi = compile("../lib/holdings-facts.ts");
let api, loader;
test.before(async () => {
  const shared = await import(
    pathToFileURL(
      path.resolve(__dirname, "../../../packages/encrypted-workspace/valuation/dist/index.mjs"),
    ).href
  );
  // VM fixtures cross a realm boundary; production shared functions receive ordinary same-realm values.
  const boundary = Object.fromEntries(
    Object.entries(shared).map(([k, v]) => [
      k,
      typeof v === "function" ? (...args) => v(...args.map(copy)) : v,
    ]),
  );
  api = compile("../lib/holdings-valuation.ts", {
    "../../../packages/encrypted-workspace/valuation/dist/index.mjs": boundary,
  });
  loader = compile(
    "../lib/holdings-price-loader.ts",
    { "./holdings-valuation": api },
    { setTimeout, clearTimeout },
  );
});
function facts() {
  const f = factsApi.editHoldings({
    content: null,
    base: null,
    snapshotId: "snapshot_PRIVATE",
    at,
    newAccount: { accountId: "account_PRIVATE", displayName: "Synthetic" },
    edit: {
      accountId: "account_PRIVATE",
      assetId: null,
      instrument: {
        symbol: "USDSTOCK",
        market: "XNAS",
        currency: "USD",
        name: "Synthetic USD",
        assetType: "stock",
      },
      quantity: "2",
      unitCost: "7",
    },
  });
  const p = f.data.accounts[0].positions[0];
  f.data.accounts[0].positions.push({
    ...copy(p),
    assetId: "asset_CAD",
    instrument: { symbol: "CADSTOCK", market: "XTSE", currency: "CAD" },
    quantity: "5",
    unitCost: { currency: "CAD", amount: "1" },
    bookCost: { currency: "CAD", amount: "5" },
  });
  return copy(f);
}
const batch = (items, profile = "folioview.quote-batch.v1") => ({
  contractVersion: "folioview.valuation.v1",
  profile,
  snapshotId: "price_snapshot",
  fetchedAt: at,
  items,
});
const quote = (instrument, price = "10", patch = {}) => ({
  instrument: copy(instrument),
  price,
  status: "available",
  source: "yahoo_finance",
  sourceAsOf: at,
  sourceDate: null,
  fetchedAt: at,
  reason: null,
  ...patch,
});
const rate = (base, amount) => ({
  base,
  quote: "CAD",
  rate: amount,
  status: "available",
  source: "bank_of_canada",
  sourceAsOf: null,
  sourceDate: day,
  fetchedAt: at,
  reason: null,
  route: {
    kind: "direct",
    via: null,
    legs: [{ base, quote: "CAD", rate: amount, sourceDate: day }],
  },
});
function prices(f = facts()) {
  return {
    quotes: [batch(api.instruments(f).map((i) => quote(i, i.currency === "USD" ? "10" : "2")))],
    fx: batch([rate("USD", "2"), rate("CNY", "0.5")], "folioview.fx-batch.v1"),
    readAt: Date.parse(at),
  };
}
const reply = (body) =>
  new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });
const tick = () => new Promise((r) => setImmediate(r));
test("one coherent CAD observation prices USD/CAD in CNY, keeps native quotes and derives switches without network or mutation", () => {
  const f = facts(),
    source = JSON.stringify(f),
    p = prices(f),
    cny = api.valuePortfolio(f, p, "CNY"),
    cad = api.valuePortfolio(f, p, "CAD");
  assert.deepEqual(copy(api.displayCurrencies(f, "CNY")), ["CNY", "USD", "CAD"]);
  assert.equal(cny.subtotal, "100");
  assert.equal(cad.subtotal, "50");
  assert.equal(cny.complete, true);
  assert.deepEqual(copy(cny.rows.map((r) => [r.value, r.weightPercent])), [
    ["80", "80"],
    ["20", "20"],
  ]);
  assert.equal(p.quotes[0].items[0].price, "10");
  assert.equal(JSON.stringify(f), source);
  assert.equal(api.displayFx(p.fx, ["USD", "CAD"], "CNY").items[0].route.kind, "cross");
  assert.equal(api.money(cny.subtotal, "CNY"), "CNY 100.00");
  f.data.accounts[0].balances = [{ currency: "CAD", cashBalance: "-100.125", buyingPower: null }];
  assert.equal(api.valuePortfolio(f, p, "CNY").subtotal, "100");
  assert.equal(api.sumAmounts(["-100.125", "2.0001"]), "-98.1249");
  assert.equal(api.money("-98.125", "CAD"), "CAD -98.12");
});
test("large quantities, fractional values and global weights stay exact across more than one50-instrument batch", () => {
  const f = facts(),
    p = f.data.accounts[0].positions[0];
  p.quantity = "9007199254740993.125";
  const data = prices(f);
  data.quotes[0].items[0].price = "1.25";
  const v = api.valuePortfolio(f, data, "CNY");
  assert.equal(v.subtotal, "45035996273704985.625");
  assert.equal(api.money(v.subtotal, "CNY"), "CNY 45,035,996,273,704,985.62");
  const many = facts();
  many.data.accounts[0].positions = Array.from({ length: 51 }, (_, n) => ({
    ...copy(p),
    assetId: `asset_${n}`,
    instrument: { symbol: `S${n}`, market: "XNAS", currency: "USD" },
    quantity: "1",
  }));
  const groups = api
    .chunks(api.instruments(many), 50)
    .map((g) => batch(g.map((i) => quote(i, "1"))));
  const result = api.valuePortfolio(
    many,
    { quotes: groups, fx: api.missingFx(at), readAt: 1 },
    "USD",
  );
  assert.equal(result.subtotal, "51");
  assert.equal(result.rows.length, 51);
  assert.equal(result.complete, true);
  assert.ok(result.rows.every((r) => r.weightPercent === "1.960784"));
});
test("missing prices/FX and unknown markets produce explicit coverage, never zero or a fabricated full denominator", () => {
  const f = facts(),
    p = prices(f);
  p.quotes[0].items[1] = {
    ...p.quotes[0].items[1],
    price: null,
    status: "missing",
    source: "none",
    sourceAsOf: null,
    reason: "upstream_unavailable",
  };
  let v = api.valuePortfolio(f, p, "CNY");
  assert.equal(v.subtotal, "80");
  assert.equal(v.complete, false);
  assert.equal(v.rows[1].status, "missing_quote");
  assert.equal(v.rows[1].weightPercent, null);
  v = api.valuePortfolio(f, { ...p, fx: api.missingFx(at) }, "CNY");
  assert.equal(v.subtotal, null);
  assert.equal(v.rows[0].status, "missing_fx");
  f.data.accounts[0].positions[0].instrument.market = "UNKNOWN";
  v = api.valuePortfolio(f, p, "USD");
  assert.equal(
    v.rows.find((r) => r.assetId === f.data.accounts[0].positions[0].assetId).status,
    "unresolved",
  );
  assert.equal(api.money(null, "USD"), "—");
});
test("reported cash converts exactly with signed balances and flags unavailable information", () => {
  const f = facts();
  const p = prices(f);
  f.data.accounts[0].balances = [
    { currency: "CAD", cashBalance: "25", buyingPower: null },
    { currency: "USD", cashBalance: "-5.125", buyingPower: null },
    { currency: "CNY", cashBalance: null, buyingPower: null },
    { currency: "EUR", cashBalance: "0", buyingPower: null },
    { currency: "GBP", cashBalance: "3", buyingPower: null },
  ];
  assert.ok(api.fxLegs(f, "CAD").some(({ base }) => base === "GBP"));
  assert.ok(!api.fxLegs(f, "CAD").some(({ base }) => base === "CNY" || base === "EUR"));
  assert.deepEqual(copy(api.valueReportedCash(f, p, "CAD")), {
    subtotal: "14.75",
    complete: false,
    stale: false,
  });
  f.data.accounts[0].balances = f.data.accounts[0].balances.slice(0, 2);
  p.fx.items[0].status = "stale";
  assert.deepEqual(copy(api.valueReportedCash(f, p, "CAD")), {
    subtotal: "14.75",
    complete: true,
    stale: true,
  });
  const securities = api.valuePortfolio(f, p, "CAD");
  assert.equal(securities.subtotal, "50");
  assert.equal(
    api.sumAmounts([securities.subtotal, api.valueReportedCash(f, p, "CAD").subtotal]),
    "64.75",
  );
  assert.equal(api.portfolioProfitLoss(f, securities, p).total.amount, "17");
});

test("broker valuation uses recorded market values without filling live quotes or reusing edited quantities", () => {
  const f = facts();
  f.data.editKind = "import";
  f.data.importSnapshot = { snapshotId: f.data.snapshotId, sourceRevision: 1 };
  const [usd, cad] = f.data.accounts[0].positions;
  for (const [position, amount] of [
    [usd, "21.3"],
    [cad, "10"],
  ]) {
    position.provenance.quantity = factsApi.provenance("import", at, day);
    position.reportedValues = {
      unitPrice: null,
      marketValue: { currency: position.instrument.currency, amount },
      unrealizedReturn: null,
    };
  }
  usd.instrument.market = "UNKNOWN";
  const market = prices(f);
  const unavailable = { ...market, quotes: [] };
  assert.equal(api.valuePortfolio(f, unavailable, "CAD").valuedCount, 0);
  const imported = api.brokerValuation(f, unavailable, "CAD");
  assert.equal(imported.complete, true);
  assert.equal(imported.subtotal, "52.6");
  assert.deepEqual(copy(imported.rows.map((r) => r.value)), ["42.6", "10"]);
  assert.equal(api.portfolioProfitLoss(f, imported, unavailable).total.amount, "19.6");
  assert.equal(
    api.brokerValuation(f, { ...unavailable, fx: api.missingFx(at) }, "CAD").rows[0].status,
    "missing_fx",
  );
  cad.reportedValues.marketValue.currency = "CNY";
  assert.ok(api.fxLegs(f, "CAD").some((pair) => pair.base === "CNY"));
  cad.reportedValues.marketValue.currency = "CAD";
  usd.provenance.quantity = factsApi.provenance("manual", at);
  assert.equal(api.brokerValuation(f, unavailable, "CAD").complete, false);
  assert.equal(api.brokerValuation(f, unavailable, "CAD").subtotal, "10");
  assert.equal(api.unitMoney("208.323569307271411", "USD"), "USD 208.32");
  assert.equal(api.unitMoney("264", "USD"), "USD 264.00");
});

test("chart grouping, tiny weights and zero holdings share the exact table denominator and retain unknown costs", () => {
  const f = facts(),
    p = f.data.accounts[0].positions[0];
  f.data.accounts[0].positions = Array.from({ length: 14 }, (_, n) => ({
    ...copy(p),
    assetId: `asset_${n}`,
    instrument: { symbol: `S${n}`, market: "XNAS", currency: "USD" },
    quantity: n === 13 ? "0.000000001" : "1",
    unitCost: null,
    bookCost: null,
    provenance: {
      ...p.provenance,
      unitCost: factsApi.provenance("unknown", at),
      bookCost: factsApi.provenance("unknown", at),
    },
  }));
  const pset = {
      quotes: [batch(api.instruments(f).map((i) => quote(i, "1")))],
      fx: api.missingFx(at),
      readAt: 1,
    },
    v = api.valuePortfolio(f, pset, "USD"),
    slices = api.allocation(f, v, "Others");
  assert.equal(slices.length, 12);
  assert.equal(slices.at(-1).positions, 3);
  assert.equal(api.sumAmounts(slices.map((s) => s.value)), v.subtotal);
  assert.equal(api.weightLabel("0.000001"), "<0.01%");
  assert.equal(api.unitMoney("0.00000001", "USD"), "USD 0.00");
  for (const row of f.data.accounts[0].positions) row.quantity = "0";
  const zero = api.valuePortfolio(f, pset, "USD");
  assert.equal(zero.subtotal, "0");
  assert.equal(zero.complete, true);
  assert.equal(api.allocation(f, zero, "Others").length, 0);
});
test("public parsing rejects private extra fields, duplicate instruments, oversized bodies and nonJSON media", async () => {
  const f = facts(),
    p = prices(f),
    signal = new AbortController().signal;
  assert.throws(() =>
    api.quoteBatch({ ...p.quotes[0], items: [...p.quotes[0].items, p.quotes[0].items[0]] }),
  );
  await assert.rejects(
    api.readPublicValuation(reply({ ...p.quotes[0], quantity: "SECRET" }), api.quoteBatch, signal),
  );
  await assert.rejects(
    api.readPublicValuation(
      new Response("{}", { headers: { "content-type": "text/plain" } }),
      api.quoteBatch,
      signal,
    ),
  );
  await assert.rejects(
    api.readPublicValuation(
      new Response(" ".repeat(128 * 1024 + 1), { headers: { "content-type": "application/json" } }),
      api.quoteBatch,
      signal,
    ),
  );
});
test("fresh cached prices use two query-only transports at most, reuse the visit and fetch no holdings, costs or credentials", async () => {
  const f = facts(),
    p = prices(f),
    calls = [],
    updates = [];
  let active = 0,
    peak = 0;
  const run = await loader.loadHoldingsPrices({
    facts: f,
    currency: "CNY",
    refresh: false,
    origin: "https://market.invalid",
    signal: new AbortController().signal,
    now: () => Date.parse(at),
    publish: (v, g) => updates.push({ v, g }),
    fetch: async (url, init) => {
      calls.push({ url, init });
      peak = Math.max(peak, ++active);
      await tick();
      active--;
      return reply(url.includes("/fx") ? p.fx : p.quotes[0]);
    },
  });
  assert.equal(run.error, false);
  assert.equal(calls.length, 2);
  assert.equal(peak, 2);
  assert.equal(updates.filter((u) => u.g.phase === "cache").at(-1).g.done, 2);
  for (const { init } of calls) {
    const body = JSON.parse(init.body);
    assert.equal(init.credentials, "omit");
    assert.deepEqual(Object.keys(init.headers), ["Content-Type"]);
    assert.ok(!JSON.stringify(body).includes("PRIVATE"));
    assert.ok(!JSON.stringify(body).includes("quantity"));
  }
  const same = await loader.loadHoldingsPrices({
    facts: f,
    currency: "CNY",
    previous: run.prices,
    refresh: false,
    origin: "",
    signal: new AbortController().signal,
    now: () => Date.parse(at) + 1,
    publish() {},
    fetch: async () => {
      throw Error("unexpected revisit fetch");
    },
  });
  assert.equal(same.error, false);
  assert.equal(api.valuePortfolio(f, same.prices, "CAD").subtotal, "50");
});
test("native-style fetch receiver supports manual holdings cache reads and quote/FX refreshes", async () => {
  for (const [quantity, unitCost, subtotal] of [
    ["2", "150", "560"],
    ["3", "155", "840"],
  ]) {
    const f = factsApi.editHoldings({
      content: null,
      base: null,
      snapshotId: "snapshot_SYNTHETIC",
      at,
      newAccount: { accountId: "manual_account", displayName: "Synthetic manual account" },
      edit: {
        accountId: "manual_account",
        assetId: null,
        instrument: {
          symbol: "AAPL",
          market: "XNAS",
          currency: "USD",
          name: "Synthetic fixture",
          assetType: "stock",
        },
        quantity,
        unitCost,
      },
    });
    const calls = [];
    const result = await loader.loadHoldingsPrices({
      facts: f,
      currency: "CAD",
      refresh: false,
      origin: "https://market.invalid",
      signal: new AbortController().signal,
      now: () => Date.parse(at),
      publish() {},
      fetch: function (url, init) {
        "use strict";
        // A browser native fetch rejects the loader's arbitrary options object as its receiver.
        assert.equal(this, undefined);
        calls.push({ url, body: JSON.parse(init.body), credentials: init.credentials });
        const cached = url.endsWith("cached=true"),
          fx = url.includes("/fx");
        return Promise.resolve(
          reply(
            fx
              ? cached
                ? batch(
                    [
                      {
                        base: "USD",
                        quote: "CAD",
                        rate: null,
                        status: "missing",
                        source: "none",
                        sourceAsOf: null,
                        sourceDate: null,
                        fetchedAt: at,
                        reason: "upstream_unavailable",
                        route: null,
                      },
                    ],
                    "folioview.fx-batch.v1",
                  )
                : batch([rate("USD", "1.4")], "folioview.fx-batch.v1")
              : cached
                ? api.missingQuotes(api.instruments(f), at)
                : batch(api.instruments(f).map((i) => quote(i, "200"))),
          ),
        );
      },
    });
    assert.equal(result.error, false, JSON.stringify(calls));
    assert.equal(calls.length, 4);
    assert.deepEqual(
      calls.map((c) => c.url),
      [
        "/api/valuation/quotes?cached=true",
        "/api/valuation/fx?cached=true",
        "/api/valuation/quotes",
        "/api/valuation/fx",
      ].map((p) => "https://market.invalid" + p),
    );
    for (const call of calls) {
      assert.equal(call.credentials, "omit");
      assert.deepEqual(
        call.body,
        call.url.includes("/quotes")
          ? { instruments: [{ symbol: "AAPL", market: "XNAS", currency: "USD" }] }
          : { pairs: [{ base: "USD", quote: "CAD" }] },
      );
    }
    const valued = api.valuePortfolio(f, result.prices, "CAD");
    assert.equal(valued.valuedCount, 1);
    assert.equal(valued.complete, true);
    assert.equal(valued.subtotal, subtotal);
  }
});
test("large cold sources fill every batch serially and never loop on missing quotes", async () => {
  const f = facts(),
    seed = f.data.accounts[0].positions[0];
  f.data.accounts[0].positions = Array.from({ length: 53 }, (_, n) => ({
    ...copy(seed),
    assetId: `asset_${n}`,
    instrument: { symbol: `S${n}`, market: "XNAS", currency: "USD" },
  }));
  const calls = [];
  let inFlight = 0;
  const result = await loader.loadHoldingsPrices({
    facts: f,
    currency: "USD",
    refresh: false,
    origin: "",
    signal: new AbortController().signal,
    now: () => Date.parse(at),
    publish() {},
    fetch: async (url, init) => {
      const body = JSON.parse(init.body);
      calls.push({ url, body });
      if (body.pairs) return reply(batch([rate("USD", "2")], "folioview.fx-batch.v1"));
      if (url.endsWith("quotes")) {
        assert.equal(++inFlight, 1);
        await tick();
        inFlight--;
      }
      return reply(api.missingQuotes(body.instruments, at));
    },
  });
  const cache = calls.filter((c) => c.url.includes("quotes?")),
    refresh = calls.filter((c) => c.url.endsWith("quotes"));
  assert.deepEqual(
    cache.map((c) => c.body.instruments.length),
    [50, 3],
  );
  assert.equal(refresh.length, 14);
  assert.deepEqual(
    refresh.flatMap((c) => c.body.instruments.map((i) => i.symbol)),
    f.data.accounts[0].positions.map((position) => position.instrument.symbol),
  );
  assert.ok(refresh.every((c) => c.body.instruments.length <= 4));
  assert.equal(result.prices.quotes.flatMap((b) => b.items).length, 53);
  assert.equal(api.valuePortfolio(f, result.prices, "USD").subtotal, null);
});
test("a cold 22-position import fills every quote and stops early if the service limits a pass", async () => {
  const f = facts();
  const seed = f.data.accounts[0].positions[0];
  f.data.accounts[0].positions = Array.from({ length: 22 }, (_, n) => ({
    ...copy(seed),
    assetId: `asset_${n}`,
    instrument: { ...seed.instrument, symbol: `S${n}` },
  }));
  for (const [limited, expectedCalls, expectedValued] of [
    [false, 6, 22],
    [true, 2, 4],
  ]) {
    let calls = 0;
    const result = await loader.loadHoldingsPrices({
      facts: f,
      currency: "USD",
      refresh: false,
      origin: "",
      signal: new AbortController().signal,
      now: () => Date.parse(at),
      publish() {},
      fetch: async (url, init) => {
        const { instruments } = JSON.parse(init.body);
        if (url.endsWith("?cached=true")) return reply(api.missingQuotes(instruments, at));
        if (++calls === 2 && limited) return new Response("{}", { status: 429 });
        return reply(batch(instruments.map((instrument) => quote(instrument, "42.12"))));
      },
    });
    assert.equal(calls, expectedCalls);
    assert.equal(result.error, limited);
    assert.equal(api.valuePortfolio(f, result.prices, "USD").valuedCount, expectedValued);
  }
});
test("recent cache entries for an earlier session skip quote round trips while expired and missing quotes refresh", async () => {
  const f = facts();
  const recent = Date.parse(at);
  const market = prices(f);
  const [first, second] = market.quotes[0].items;
  const staleQuotes = batch(
    [first, second].map((row) => ({
      ...row,
      sourceAsOf: "2026-11-12T21:00:00Z",
      status: "stale",
    })),
  );
  for (const [elapsed, expected] of [
    [1000, 0],
    [15 * 60 * 1000, 1],
  ]) {
    const refreshed = [];
    await loader.loadHoldingsPrices({
      facts: f,
      currency: "CAD",
      refresh: true,
      origin: "",
      signal: new AbortController().signal,
      now: () => recent + elapsed,
      publish() {},
      fetch: async (url, { body }) => {
        if (url.includes("/fx")) return reply(batch([rate("USD", "2")], "folioview.fx-batch.v1"));
        if (url.endsWith("?cached=true")) return reply(staleQuotes);
        refreshed.push(...JSON.parse(body).instruments);
        return reply(staleQuotes);
      },
    });
    assert.equal(refreshed.length, expected * 2);
  }
});
test("abort prevents any late publication even if an obsolete transport resolves; fresh default changes only request missing FX", async () => {
  const f = facts(),
    controller = new AbortController(),
    updates = [];
  let resolve;
  const pending = new Promise((r) => (resolve = r)),
    work = loader.loadHoldingsPrices({
      facts: f,
      currency: "USD",
      refresh: false,
      origin: "",
      signal: controller.signal,
      publish: (v) => updates.push(v),
      fetch: () => pending,
      now: () => Date.parse(at),
    });
  await tick();
  controller.abort();
  const count = updates.length;
  await assert.rejects(work);
  resolve(reply(prices(f).quotes[0]));
  await tick();
  assert.equal(updates.length, count);
  const p = prices(f);
  p.fx = batch([rate("USD", "2")], "folioview.fx-batch.v1");
  let calls = 0;
  const next = await loader.loadHoldingsPrices({
    facts: f,
    currency: "CNY",
    previous: p,
    refresh: false,
    origin: "",
    signal: new AbortController().signal,
    publish() {},
    now: () => Date.parse(at) + 1,
    fetch: async (url) => {
      calls++;
      assert.ok(url.includes("/fx"));
      return reply(prices(f).fx);
    },
  });
  assert.equal(calls, 1);
  assert.equal(api.valuePortfolio(f, next.prices, "CNY").subtotal, "100");
});
test("private display hook masks lock/generation changes, resets invalid selections, and switching currency never reopens ciphertext or refetches", async () => {
  const h = hooks(),
    cache = compile("../lib/workspace-cache.ts"),
    displayCache = new cache.WorkspaceDisplayCache();
  displayCache.bind("owner_A:1");
  let calls = 0,
    defaultCurrency = "CNY";
  const model = {
    owner: "owner_A",
    authenticated: true,
    phase: "unlocked",
    selectedSourceId: "source_PRIVATE",
    displayCache,
    content: facts(),
    sourceMetadata: {
      state: "active",
      source: { resourceRef: { incarnation: "inc_A" }, sourceEpoch: 1 },
      authorityVersion: 1,
    },
  };
  const hook = compile(
    "../components/useHoldingsValuation.ts",
    {
      react: { ...h.react, useMemo: (f) => f() },
      "@/lib/holdings-facts": factsApi,
      "@/lib/holdings-valuation": api,
      "@/lib/holdings-price-loader": loader,
    },
    {
      process: { env: {} },
      fetch: async (url) => {
        calls++;
        return reply(url.includes("/fx") ? prices().fx : prices().quotes[0]);
      },
    },
  );
  const render = () => h.render(() => hook.useHoldingsValuation(model, defaultCurrency));
  render();
  await tick();
  await tick();
  let v = render();
  assert.equal(v.valuation.subtotal, "100");
  assert.equal(calls, 2);
  v.select("CAD");
  v = render();
  assert.equal(v.valuation.subtotal, "50");
  assert.equal(calls, 2);
  defaultCurrency = "USD";
  v = render();
  assert.equal(v.currency, "USD");
  await tick();
  await tick();
  render();
  assert.equal(calls, 2);
  model.phase = "locked";
  displayCache.bind(null);
  v = render();
  assert.equal(v.valuation, null);
  assert.equal(v.facts, null);
  assert.equal(displayCache.valuations.size, 0);
  model.phase = "unlocked";
  displayCache.bind("owner_A:2");
  v = render();
  assert.equal(v.valuation?.subtotal ?? null, null);
  h.close();
});
test("explicit refresh rereads available server caches; failed updates preserve dated stale values and a cached error", async () => {
  const f = facts(),
    original = prices(f),
    calls = [];
  const fresh = await loader.loadHoldingsPrices({
    facts: f,
    currency: "CNY",
    previous: original,
    refresh: true,
    origin: "",
    signal: new AbortController().signal,
    now: () => Date.parse(at) + 1,
    publish() {},
    fetch: async (url) => {
      calls.push(url);
      return reply(url.includes("/fx") ? original.fx : original.quotes[0]);
    },
  });
  assert.equal(calls.length, 2);
  assert.ok(calls.every((u) => u.endsWith("cached=true")));
  assert.equal(fresh.error, false);
  const failed = await loader.loadHoldingsPrices({
    facts: f,
    currency: "CNY",
    previous: original,
    refresh: true,
    origin: "",
    signal: new AbortController().signal,
    now: () => Date.parse(at) + 2,
    publish() {},
    fetch: async () => {
      throw Error("private provider diagnostic");
    },
  });
  assert.equal(failed.error, true);
  assert.equal(failed.prices.error, true);
  assert.equal(api.valuePortfolio(f, failed.prices, "CNY").subtotal, "100");
  assert.equal(api.valuePortfolio(f, failed.prices, "CNY").stale, true);
  const revisit = await loader.loadHoldingsPrices({
    facts: f,
    currency: "CNY",
    previous: failed.prices,
    refresh: false,
    origin: "",
    signal: new AbortController().signal,
    now: () => Date.parse(at) + 3,
    publish() {},
    fetch: async () => {
      throw Error("unexpected immediate retry");
    },
  });
  assert.equal(revisit.error, true);
  assert.equal(JSON.stringify(revisit).includes("diagnostic"), false);
});
test("single-currency sources do not request unused FX, and disconnected owner history remains a readable display", async () => {
  const f = facts();
  f.data.accounts[0].positions.splice(1);
  assert.deepEqual(copy(api.fxLegs(f, "USD")), []);
  let calls = 0;
  await loader.loadHoldingsPrices({
    facts: f,
    currency: "USD",
    refresh: false,
    origin: "",
    signal: new AbortController().signal,
    publish() {},
    now: () => Date.parse(at),
    fetch: async (url) => {
      calls++;
      assert.ok(url.includes("quotes"));
      return reply(batch(api.instruments(f).map((i) => quote(i))));
    },
  });
  assert.equal(calls, 1);
  const h = hooks(),
    cache = compile("../lib/workspace-cache.ts"),
    c = new cache.WorkspaceDisplayCache();
  c.bind("owner:1");
  const model = {
    owner: "owner",
    authenticated: true,
    phase: "unlocked",
    selectedSourceId: "source",
    displayCache: c,
    content: f,
    sourceMetadata: {
      state: "disconnected",
      source: { resourceRef: { incarnation: "inc" }, sourceEpoch: 1 },
      authorityVersion: 1,
    },
  };
  const hook = compile(
    "../components/useHoldingsValuation.ts",
    {
      react: { ...h.react, useMemo: (f) => f() },
      "@/lib/holdings-facts": factsApi,
      "@/lib/holdings-valuation": api,
      "@/lib/holdings-price-loader": loader,
    },
    {
      process: { env: {} },
      fetch: async () => reply(batch(api.instruments(f).map((i) => quote(i)))),
    },
  );
  assert.ok(h.render(() => hook.useHoldingsValuation(model, "USD")).facts);
  h.close();
});
test("the allocation dialog changes chart type locally while preserving its currency, rows and accessible legend", () => {
  const h = hooks(),
    t = (key, values = {}) => key + Object.values(values).join(":"),
    f = facts(),
    v = api.valuePortfolio(f, prices(f), "CNY");
  const component = compile("../components/HoldingsValuation.tsx", {
    react: { ...h.react, useMemo: (f) => f() },
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    "next-intl": { useTranslations: () => t, useLocale: () => "en" },
    "./CurrencyPreferencesProvider": {},
    "./useHoldingsValuation": {},
    "@/lib/holdings-facts": factsApi,
    "@/lib/holdings-valuation": api,
    "./HoldingsValuation.module.css": { default: {} },
  });
  const render = () =>
    h.render(() =>
      component.HoldingsAllocation({ facts: f, valuation: v, identity: "scope", onClose() {} }),
    );
  let tree = render();
  assert.ok(JSON.stringify(tree).includes("CNY 100.00"));
  assert.equal(all(tree, (n) => n.type === "li").length, 2);
  all(tree, (n) => n.type === "button" && n.props.children === "bar")[0].props.onClick();
  tree = render();
  assert.ok(all(tree, (n) => n.type === "div" && n.props["data-kind"] === "bar").length);
  assert.equal(all(tree, (n) => n.type === "li").length, 2);
  assert.ok(JSON.stringify(tree).includes("CNY 80.00"));
  all(tree, (n) => n.type === "button" && n.props.children === "pie")[0].props.onClick();
  tree = render();
  assert.ok(all(tree, (n) => n.type === "div" && n.props["data-kind"] === "pie").length);
  h.close();
});
test("synchronous private-cache clearing blocks late refills before React has rendered the lock/hidden transition", async () => {
  const h = hooks(),
    Cache = compile("../lib/workspace-cache.ts").WorkspaceDisplayCache,
    c = new Cache();
  c.bind("owner:1");
  const f = facts(),
    model = {
      owner: "owner",
      authenticated: true,
      phase: "unlocked",
      selectedSourceId: "source",
      displayCache: c,
      content: f,
      sourceMetadata: {
        state: "active",
        source: { resourceRef: { incarnation: "inc" }, sourceEpoch: 1 },
        authorityVersion: 1,
      },
    };
  let resolve;
  const wait = new Promise((r) => (resolve = r));
  const hook = compile(
    "../components/useHoldingsValuation.ts",
    {
      react: { ...h.react, useMemo: (f) => f() },
      "@/lib/holdings-facts": factsApi,
      "@/lib/holdings-valuation": api,
      "@/lib/holdings-price-loader": loader,
    },
    {
      process: { env: {} },
      fetch: async (url) => {
        await wait;
        return reply(url.includes("/fx") ? prices(f).fx : prices(f).quotes[0]);
      },
    },
  );
  h.render(() => hook.useHoldingsValuation(model, "CNY"));
  assert.equal(c.valuations.size, 1);
  const before = c.revision;
  c.clear();
  assert.ok(c.revision > before);
  resolve();
  await tick();
  await tick();
  assert.equal(c.valuations.size, 0);
  h.close();
});
test("inactive pages make no price requests and valid display selection survives category unmount; default changes reset it", async () => {
  const Cache = compile("../lib/workspace-cache.ts").WorkspaceDisplayCache,
    c = new Cache();
  c.bind("owner:1");
  let calls = 0;
  const f = facts(),
    model = {
      owner: "owner",
      authenticated: true,
      phase: "unlocked",
      selectedSourceId: "source",
      displayCache: c,
      content: f,
      sourceMetadata: {
        state: "active",
        source: { resourceRef: { incarnation: "inc" }, sourceEpoch: 1 },
        authorityVersion: 1,
      },
    };
  function mount() {
    const h = hooks(),
      hook = compile(
        "../components/useHoldingsValuation.ts",
        {
          react: { ...h.react, useMemo: (f) => f() },
          "@/lib/holdings-facts": factsApi,
          "@/lib/holdings-valuation": api,
          "@/lib/holdings-price-loader": loader,
        },
        {
          process: { env: {} },
          fetch: async (url) => {
            calls++;
            return reply(url.includes("/fx") ? prices(f).fx : prices(f).quotes[0]);
          },
        },
      );
    return {
      close: h.close,
      render: (currency = "CNY", active = true) =>
        h.render(() => hook.useHoldingsValuation(model, currency, active)),
    };
  }
  const a = mount();
  a.render("CNY", false);
  await tick();
  assert.equal(calls, 0);
  a.render();
  await tick();
  await tick();
  let view = a.render();
  view.select("CAD");
  assert.equal(a.render().currency, "CAD");
  assert.equal(calls, 2);
  a.render("CNY", false);
  await tick();
  assert.equal(calls, 2);
  a.close();
  const b = mount();
  view = b.render();
  assert.equal(view.currency, "CAD");
  await tick();
  await tick();
  assert.equal(calls, 2);
  assert.equal(b.render("USD").currency, "USD");
  await tick();
  await tick();
  assert.equal(b.render("CNY").currency, "CNY");
  await tick();
  await tick();
  assert.equal(calls, 2);
  b.close();
});
test("resetting a restored source currency schedules the actual component and hides reset without fetching", async () => {
  const Cache = compile("../lib/workspace-cache.ts").WorkspaceDisplayCache,
    displayCache = new Cache();
  displayCache.bind("owner:1");
  const f = facts(),
    model = {
      owner: "owner",
      authenticated: true,
      phase: "unlocked",
      selectedSourceId: "source_A",
      editScope: "edit_A",
      displayCache,
      content: f,
      sourceMetadata: {
        state: "active",
        source: { resourceRef: { incarnation: "inc_A" }, sourceEpoch: 1 },
        authorityVersion: 1,
      },
    };
  let calls = 0;
  function mount() {
    const h = hooks();
    let scheduled = true,
      tree;
    const react = {
      ...h.react,
      useMemo: (fn) => fn(),
      useState(initial) {
        const [value, update] = h.react.useState(initial);
        return [
          value,
          (next) =>
            update((before) => {
              const after = typeof next === "function" ? next(before) : next;
              if (!Object.is(before, after)) scheduled = true;
              return after;
            }),
        ];
      },
    };
    const hook = compile(
      "../components/useHoldingsValuation.ts",
      {
        react,
        "@/lib/holdings-facts": factsApi,
        "@/lib/holdings-valuation": api,
        "@/lib/holdings-price-loader": loader,
      },
      {
        process: { env: {} },
        fetch: async (url) => {
          calls++;
          return reply(
            url.includes("/fx")
              ? batch([rate("USD", "2")], "folioview.fx-batch.v1")
              : prices(f).quotes[0],
          );
        },
      },
    );
    const component = compile("../components/HoldingsValuation.tsx", {
      react,
      "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
      "next-intl": { useTranslations: () => (key) => key, useLocale: () => "en" },
      "./CurrencyPreferencesProvider": {
        useCurrencyPreferences: () => ({ defaultPortfolioCurrency: "CAD", loaded: true }),
      },
      "./useHoldingsValuation": hook,
      "@/lib/holdings-facts": factsApi,
      "@/lib/holdings-valuation": api,
      "./HoldingsValuation.module.css": { default: {} },
    });
    return {
      close: h.close,
      flush() {
        if (scheduled) tree = h.render(() => component.default({ model }));
        scheduled = false;
        return tree;
      },
    };
  }
  const first = mount();
  first.flush();
  await tick();
  await tick();
  all(first.flush(), (n) => n.type === "select")[0].props.onChange({ target: { value: "USD" } });
  assert.equal(all(first.flush(), (n) => n.type === "select")[0].props.value, "USD");
  first.close();

  const empty = copy(f);
  empty.state = "empty";
  empty.data.snapshotId = "snapshot_EMPTY";
  empty.data.accounts.forEach((account) => {
    account.positions = [];
    account.balances = [];
  });
  model.selectedSourceId = "source_B";
  model.content = empty;
  const other = mount();
  other.flush();
  await tick();
  await tick();
  other.close();
  model.selectedSourceId = "source_A";
  model.content = f;

  const restored = mount();
  restored.flush();
  await tick();
  await tick();
  let tree = restored.flush();
  assert.equal(all(tree, (n) => n.type === "select")[0].props.value, "USD");
  const before = calls,
    reset = all(tree, (n) => n.type === "button" && n.props.children === "reset");
  assert.equal(reset.length, 1);
  reset[0].props.onClick();
  tree = restored.flush();
  assert.equal(all(tree, (n) => n.type === "select")[0].props.value, "CAD");
  assert.equal(all(tree, (n) => n.type === "button" && n.props.children === "reset").length, 0);
  await tick();
  assert.equal(calls, before);
  all(tree, (n) => n.type === "select" && n.props["aria-label"] === "profitMode")[0].props.onChange(
    { target: { value: "amount" } },
  );
  tree = restored.flush();
  assert.ok(JSON.stringify(tree).includes("+CAD 17.00"));
  await tick();
  assert.equal(calls, before, "the real price hook does not refetch for amount mode");
  all(tree, (n) => n.type === "select" && n.props["aria-label"] === "profitMode")[0].props.onChange(
    { target: { value: "percent" } },
  );
  tree = restored.flush();
  assert.ok(JSON.stringify(tree).includes("+51.52%"));
  await tick();
  assert.equal(calls, before, "the real price hook does not refetch for percentage mode");
  restored.close();
});
test("leaving the active page aborts pending quote transports without losing already cached display data", async () => {
  const h = hooks(),
    Cache = compile("../lib/workspace-cache.ts").WorkspaceDisplayCache,
    c = new Cache();
  c.bind("owner:1");
  const f = facts(),
    model = {
      owner: "owner",
      authenticated: true,
      phase: "unlocked",
      selectedSourceId: "source",
      displayCache: c,
      content: f,
      sourceMetadata: {
        state: "active",
        source: { resourceRef: { incarnation: "inc" }, sourceEpoch: 1 },
        authorityVersion: 1,
      },
    },
    signals = [];
  const hook = compile(
    "../components/useHoldingsValuation.ts",
    {
      react: { ...h.react, useMemo: (f) => f() },
      "@/lib/holdings-facts": factsApi,
      "@/lib/holdings-valuation": api,
      "@/lib/holdings-price-loader": loader,
    },
    {
      process: { env: {} },
      fetch: async (url, init) => {
        signals.push(init.signal);
        return new Promise(() => {});
      },
    },
  );
  h.render(() => hook.useHoldingsValuation(model, "CNY", true));
  assert.equal(signals.length, 2);
  const view = h.render(() => hook.useHoldingsValuation(model, "CNY", false));
  assert.equal(view.busy, false);
  assert.ok(signals.every((s) => s.aborted));
  assert.equal(c.valuations.size, 1);
  h.close();
});

test("cumulative returns use exact recorded costs and a weighted portfolio denominator, never daily fields", () => {
  const f = facts(),
    p = prices(f),
    before = JSON.stringify({ f, p });
  const cad = api.portfolioProfitLoss(f, api.valuePortfolio(f, p, "CAD"), p);
  assert.deepEqual(copy([...cad.rows.values()]), [
    { amount: "12", percent: "42.857143", reason: null },
    { amount: "5", percent: "100", reason: null },
  ]);
  assert.deepEqual(copy(cad.total), { amount: "17", percent: "51.515152", reason: null });
  assert.equal(cad.complete, true);
  const cny = api.portfolioProfitLoss(f, api.valuePortfolio(f, p, "CNY"), p);
  assert.equal(cny.total.amount, "34");
  assert.equal(cny.total.percent, cad.total.percent);
  assert.equal(api.sumAmounts([...cny.rows.values()].map((r) => r.amount)), cny.total.amount);
  assert.equal(JSON.stringify({ f, p }), before);
  // The imported broker return is not reused as a current or daily return.
  f.data.editKind = "import";
  f.data.importSnapshot = { snapshotId: f.data.snapshotId, sourceRevision: 1 };
  f.data.accounts[0].positions[0].reportedValues = {
    unitPrice: null,
    marketValue: null,
    unrealizedReturn: { currency: "USD", amount: "999" },
  };
  assert.equal(api.portfolioProfitLoss(f, api.valuePortfolio(f, p, "CAD"), p).total.amount, "17");
});

test("losses, zero quantity, zero cost and empty holdings remain signed and never divide by zero", () => {
  const f = facts(),
    p = prices(f);
  p.quotes[0].items[0].price = "1";
  let profit = api.portfolioProfitLoss(f, api.valuePortfolio(f, p, "CAD"), p);
  assert.equal([...profit.rows.values()][0].amount, "-24");
  assert.equal([...profit.rows.values()][0].percent, "-85.714286");
  assert.deepEqual(copy(profit.total), { amount: "-19", percent: "-57.575758", reason: null });
  for (const position of f.data.accounts[0].positions) position.bookCost.amount = "0";
  profit = api.portfolioProfitLoss(f, api.valuePortfolio(f, p, "CAD"), p);
  assert.deepEqual(copy(profit.total), { amount: "14", percent: null, reason: "zero_cost" });
  assert.equal([...profit.rows.values()][0].amount, "4");
  assert.equal(profit.complete, true);
  f.data.accounts[0].positions[0].quantity = "0";
  profit = api.portfolioProfitLoss(f, api.valuePortfolio(f, p, "CAD"), p);
  assert.equal([...profit.rows.values()][0].amount, "0");
  f.data.accounts[0].positions = [];
  profit = api.portfolioProfitLoss(f, api.valuePortfolio(f, p, "CAD"), p);
  assert.deepEqual(copy(profit.total), { amount: "0", percent: null, reason: "zero_cost" });
});

test("book cost outranks rounded unit cost; unit cost and recorded CAD cost are coherent fallbacks", () => {
  const f = facts(),
    p = prices(f),
    position = f.data.accounts[0].positions[0];
  position.bookCost.amount = "13.99";
  let profit = api.portfolioProfitLoss(f, api.valuePortfolio(f, p, "CAD"), p);
  assert.equal([...profit.rows.values()][0].amount, "12.02");
  position.bookCost = null;
  profit = api.portfolioProfitLoss(f, api.valuePortfolio(f, p, "CAD"), p);
  assert.equal([...profit.rows.values()][0].amount, "12");
  position.unitCost = null;
  position.bookCostCad = { currency: "CAD", amount: "30" };
  position.provenance.bookCostCad = factsApi.provenance("manual", at);
  f.data.accounts[0].positions = [position];
  assert.deepEqual(copy(api.fxLegs(f, "USD")), [{ base: "USD", quote: "CAD" }]);
  profit = api.portfolioProfitLoss(f, api.valuePortfolio(f, p, "USD"), p);
  assert.deepEqual(copy(profit.total), { amount: "5", percent: "33.333333", reason: null });
  const unavailable = { ...p, fx: api.missingFx(at) };
  profit = api.portfolioProfitLoss(f, api.valuePortfolio(f, unavailable, "USD"), unavailable);
  assert.equal(profit.complete, false);
  assert.equal(profit.total.amount, null);
  assert.equal([...profit.rows.values()][0].reason, "missing_cost_fx");
  const stale = copy(p);
  stale.fx.items[0].status = "stale";
  assert.equal(api.portfolioProfitLoss(f, api.valuePortfolio(f, stale, "USD"), stale).stale, true);
  position.bookCostCad.amount = "0";
  assert.deepEqual(copy(api.fxLegs(f, "USD")), [], "zero cost needs no conversion request");
  profit = api.portfolioProfitLoss(f, api.valuePortfolio(f, unavailable, "USD"), unavailable);
  assert.deepEqual(copy(profit.total), { amount: "20", percent: null, reason: "zero_cost" });
  position.quantity = "0";
  profit = api.portfolioProfitLoss(f, api.valuePortfolio(f, unavailable, "CAD"), unavailable);
  assert.deepEqual(copy(profit.total), { amount: "0", percent: null, reason: "zero_cost" });
});

test("unknown costs, missing quotes or FX suppress the overall return instead of reporting a partial total as complete", () => {
  const f = facts(),
    p = prices(f),
    position = f.data.accounts[0].positions[0];
  position.bookCost = position.unitCost = null;
  let profit = api.portfolioProfitLoss(f, api.valuePortfolio(f, p, "CAD"), p);
  assert.equal([...profit.rows.values()][0].reason, "missing_cost");
  assert.equal(profit.total.amount, null);
  assert.equal(profit.total.percent, null);
  assert.equal(profit.knownCount, 1);
  assert.equal(profit.complete, false);
  p.quotes[0] = api.missingQuotes(api.instruments(f), at);
  profit = api.portfolioProfitLoss(f, api.valuePortfolio(f, p, "CAD"), p);
  assert.equal(profit.knownCount, 0);
  assert.ok([...profit.rows.values()].every((r) => r.reason === "missing_value"));
  const noFx = { ...prices(f), fx: api.missingFx(at) };
  profit = api.portfolioProfitLoss(f, api.valuePortfolio(f, noFx, "CNY"), noFx);
  assert.equal(profit.total.amount, null);
});

test("large fractional costs and display rounding retain exact signed returns", () => {
  const f = facts(),
    p = prices(f),
    position = f.data.accounts[0].positions[0];
  f.data.accounts[0].positions = [position];
  position.quantity = "9007199254740993.125";
  position.bookCost = null;
  position.unitCost.amount = "1.00000001";
  p.quotes[0].items[0].price = "1";
  const profit = api.portfolioProfitLoss(f, api.valuePortfolio(f, p, "USD"), p);
  assert.equal(profit.total.amount, "-90071992.54740993125");
  assert.equal(api.profitLossLabel(profit.total.amount, "amount", "USD"), "−USD 90,071,992.55");
  assert.equal(api.profitLossLabel("-0.001", "percent", "CAD"), "−<0.01%");
  assert.equal(api.profitLossLabel("0.001", "amount", "CAD"), "+CAD <0.01");
  assert.equal(api.profitLossLabel("-0.1", "amount", "JPY"), "−JPY <1");
  assert.equal(api.profitLossLabel("0", "percent", "CAD"), "0.00%");
  assert.equal(api.profitLossLabel(null, "amount", "CAD"), "—");
});

test("one default-percentage control switches every position and the overall return together, preserving mode across currency changes", () => {
  const h = hooks(),
    f = facts(),
    p = prices(f),
    view = {
      facts: f,
      prices: p,
      currency: "CAD",
      options: ["CAD", "USD"],
      isDefault: true,
      valuation: api.valuePortfolio(f, p, "CAD"),
      select(currency) {
        this.currency = currency;
        this.valuation = api.valuePortfolio(f, p, currency);
      },
    };
  const component = compile(
    "../components/HoldingsValuation.tsx",
    {
      react: { ...h.react, useMemo: (fn) => fn() },
      "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
      "next-intl": { useTranslations: () => (key) => key, useLocale: () => "en" },
      "./CurrencyPreferencesProvider": {
        useCurrencyPreferences: () => ({ defaultPortfolioCurrency: "CAD", loaded: true }),
      },
      "./useHoldingsValuation": { useHoldingsValuation: () => view },
      "@/lib/holdings-facts": factsApi,
      "@/lib/holdings-valuation": api,
      "./HoldingsValuation.module.css": { default: {} },
    },
    {
      fetch() {
        assert.fail("display toggles must not fetch");
      },
    },
  );
  const render = () => h.render(() => component.default({ model: { editScope: "scope" } }));
  let tree = render(),
    text = JSON.stringify(tree);
  assert.equal(all(tree, (n) => n.props?.["aria-label"] === "profitMode").length, 1);
  assert.equal(
    all(tree, (n) => n.type === "select" && n.props["aria-label"] === "profitMode")[0].props.value,
    "percent",
  );
  for (const result of ["+51.52%", "+42.86%", "+100.00%"]) assert.ok(text.includes(result), result);
  all(tree, (n) => n.type === "select" && n.props["aria-label"] === "profitMode")[0].props.onChange(
    { target: { value: "amount" } },
  );
  tree = render();
  text = JSON.stringify(tree);
  for (const result of ["+CAD 17.00", "+CAD 12.00", "+CAD 5.00"])
    assert.ok(text.includes(result), result);
  assert.ok(!text.includes("+42.86%"));
  all(tree, (n) => n.type === "select")[0].props.onChange({ target: { value: "USD" } });
  text = JSON.stringify(render());
  for (const result of ["+USD 8.50", "+USD 6.00", "+USD 2.50"])
    assert.ok(text.includes(result), result);
  all(
    render(),
    (n) => n.type === "select" && n.props["aria-label"] === "profitMode",
  )[0].props.onChange({ target: { value: "percent" } });
  assert.ok(JSON.stringify(render()).includes("+51.52%"));
  h.close();
});
