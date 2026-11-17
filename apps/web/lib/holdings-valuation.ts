/** Public prices; private quantities and exact valuation never leave this browser. */
import {
  crossRate,
  displayCurrencies,
  fxBatch,
  quoteBatch,
  roundDisplayAmount,
  valueHoldings,
  type Batch,
  type Currency,
  type FxItem,
  type HoldingsFacts,
  type Instrument,
  type Pair,
  type QuoteItem,
  type Valuation,
} from "../../../packages/encrypted-workspace/valuation/dist/index.mjs";

export type PriceSet = {
  quotes: Batch<QuoteItem>[];
  fx: Batch<FxItem>;
  readAt: number;
  error?: boolean;
  displaySelection?: { currency: Currency; defaultCurrency: Currency };
};
export type HoldingsValuation = Omit<Valuation, "quoteSnapshotId"> & {
  quoteSnapshotIds: string[];
};
export type ProfitLossMode = "percent" | "amount";
export type ProfitLoss = {
  amount: string | null;
  percent: string | null;
  reason: "missing_value" | "missing_cost" | "missing_cost_fx" | "zero_cost" | null;
};
type Position = HoldingsFacts["data"]["accounts"][number]["positions"][number];
function costBasis(position: Position) {
  if (decimal(position.quantity).n === BigInt(0))
    return { currency: position.instrument.currency, amount: "0" };
  return (
    position.bookCost ??
    (position.unitCost
      ? {
          currency: position.unitCost.currency,
          amount: multiplyAmounts(position.quantity, position.unitCost.amount),
        }
      : position.bookCostCad)
  );
}
export const instrumentKey = (
  i: Instrument | { symbol: string | null; market: string; currency: Currency },
) => JSON.stringify([i.symbol, i.market, i.currency]);
export function instruments(facts: HoldingsFacts): Instrument[] {
  const found = new Map<string, Instrument>();
  for (const a of facts.data.accounts)
    for (const p of a.positions)
      if (p.instrument.symbol && p.instrument.market !== "UNKNOWN" && p.assetType !== "unsupported")
        found.set(instrumentKey(p.instrument), p.instrument as Instrument);
  return [...found.values()];
}
export function chunks<T>(rows: T[], size: number): T[][] {
  return Array.from({ length: Math.ceil(rows.length / size) }, (_, n) =>
    rows.slice(n * size, (n + 1) * size),
  );
}
export function fxLegs(facts: HoldingsFacts, currency: Currency): Pair[] {
  const currencies = [
    ...new Set([
      ...displayCurrencies(facts, currency),
      ...facts.data.accounts.flatMap((a) =>
        a.positions.flatMap((p) => {
          const cost = costBasis(p);
          return cost && decimal(cost.amount).n !== BigInt(0) ? [cost.currency] : [];
        }),
      ),
    ]),
  ];
  return currencies.length < 2
    ? []
    : currencies.filter((c) => c !== "CAD").map((base) => ({ base, quote: "CAD" }));
}
function emptyBatch(profile: string, at: string) {
  return {
    contractVersion: "folioview.valuation.v1" as const,
    profile,
    snapshotId: "unavailable",
    fetchedAt: at,
    items: [],
  };
}
export function missingQuotes(items: Instrument[], at: string): Batch<QuoteItem> {
  return {
    ...emptyBatch("folioview.quote-batch.v1", at),
    items: items.map((instrument) => ({
      instrument,
      price: null,
      source: "none",
      status: "missing",
      sourceAsOf: null,
      sourceDate: null,
      fetchedAt: at,
      reason: "upstream_unavailable",
    })),
  };
}
export function missingFx(at: string): Batch<FxItem> {
  return emptyBatch("folioview.fx-batch.v1", at);
}

/** Derive every display cross from one observation; switches never fetch another FX date. */
export function displayFx(
  legs: Batch<FxItem>,
  natives: Currency[],
  currency: Currency,
): Batch<FxItem> {
  legs = fxBatch(legs);
  const items: FxItem[] = [...new Set(natives)]
    .filter((c) => c !== currency)
    .map((base) => {
      const left = legs.items.find((i) => i.base === base && i.quote === "CAD"),
        right = legs.items.find((i) => i.base === currency && i.quote === "CAD");
      const available = (i: FxItem | undefined) =>
        i && ["available", "stale"].includes(i.status) && i.rate;
      const required = [base === "CAD" ? null : left, currency === "CAD" ? null : right].filter(
        (i): i is FxItem => Boolean(i),
      );
      const complete =
        (base === "CAD" || available(left)) && (currency === "CAD" || available(right));
      const sourceDate = required[0]?.sourceDate ?? null;
      if (!complete || !sourceDate || required.some((i) => i.sourceDate !== sourceDate))
        return {
          base,
          quote: currency,
          rate: null,
          source: "none",
          status: "missing",
          sourceAsOf: null,
          sourceDate: null,
          fetchedAt: legs.fetchedAt,
          route: null,
          reason: "upstream_unavailable",
        };
      return {
        base,
        quote: currency,
        rate: crossRate(
          base === "CAD" ? "1" : left!.rate!,
          currency === "CAD" ? "1" : right!.rate!,
        ),
        source: "bank_of_canada",
        status: required.some((i) => i.status === "stale") ? "stale" : "available",
        sourceAsOf: required[0].sourceAsOf,
        sourceDate,
        fetchedAt: legs.fetchedAt,
        reason: null,
        route: {
          kind: currency === "CAD" ? "direct" : base === "CAD" ? "inverse" : "cross",
          via: base !== "CAD" && currency !== "CAD" ? "CAD" : null,
          legs: required.map((i) => ({ base: i.base, quote: "CAD", rate: i.rate!, sourceDate })),
        },
      };
    });
  return fxBatch({
    ...legs,
    snapshotId: `view_${currency}_${legs.snapshotId}`.slice(0, 128),
    items,
  });
}

// Values are already validated shared-adapter outputs, bounded to80 integer/60 fractional digits.
function decimal(value: string, signed = false) {
  if (
    !(
      signed ? /^-?(0|[1-9][0-9]{0,79})(\.[0-9]{1,60})?$/ : /^(0|[1-9][0-9]{0,79})(\.[0-9]{1,60})?$/
    ).test(value)
  )
    throw Error("invalid_valuation");
  const [whole, tail = ""] = value.split(".");
  return { n: BigInt(whole + tail), scale: tail.length };
}
function plain(n: bigint, scale: number) {
  const value = String(n < BigInt(0) ? -n : n).padStart(scale + 1, "0");
  return (
    (n < BigInt(0) ? "-" : "") +
    (scale
      ? (value.slice(0, -scale) + "." + value.slice(-scale)).replace(/0+$/, "").replace(/\.$/, "")
      : value)
  );
}
export function sumAmounts(values: string[]): string {
  const rows = values.map((v) => decimal(v, true)),
    scale = Math.max(0, ...rows.map((r) => r.scale));
  return plain(
    rows.reduce((n, r) => n + r.n * BigInt(10) ** BigInt(scale - r.scale), BigInt(0)),
    scale,
  );
}
function multiplyAmounts(left: string, right: string): string {
  const a = decimal(left),
    b = decimal(right);
  return plain(a.n * b.n, a.scale + b.scale);
}
function difference(value: string, cost: string): string {
  return sumAmounts([value, decimal(cost).n === BigInt(0) ? "0" : `-${cost}`]);
}
function returnPercent(amount: string, cost: string): string | null {
  const negative = amount.startsWith("-"),
    result = percentage(negative ? amount.slice(1) : amount, cost);
  return result === null || result === "0" ? result : `${negative ? "-" : ""}${result}`;
}
/** Unrealized return on current positions, never daily change or an average of row returns. */
export function portfolioProfitLoss(
  facts: HoldingsFacts,
  valuation: HoldingsValuation,
  prices: PriceSet,
) {
  const positions = new Map(
      facts.data.accounts.flatMap((a) =>
        a.positions.map((p) => [JSON.stringify([a.accountId, p.assetId]), p] as const),
      ),
    ),
    costs = new Map([...positions].map(([key, p]) => [key, costBasis(p)])),
    fx = displayFx(
      prices.fx,
      [...costs.values()].flatMap((cost) => (cost ? [cost.currency] : [])),
      valuation.currency,
    ),
    rates = new Map(fx.items.map((item) => [item.base, item])),
    rows = new Map<string, ProfitLoss>(),
    knownCosts: string[] = [],
    knownReturns: string[] = [];
  let stale = false;
  for (const row of valuation.rows) {
    const key = JSON.stringify([row.accountId, row.assetId]),
      cost = costs.get(key),
      rate = cost ? rates.get(cost.currency) : undefined,
      zeroCost = cost && decimal(cost.amount).n === BigInt(0);
    let reason: ProfitLoss["reason"] = null,
      amount: string | null = null,
      percent: string | null = null;
    if (row.value === null) reason = "missing_value";
    else if (!cost) reason = "missing_cost";
    else if (!zeroCost && cost.currency !== valuation.currency && !rate?.rate)
      reason = "missing_cost_fx";
    else {
      const converted = zeroCost
        ? "0"
        : cost.currency === valuation.currency
          ? cost.amount
          : multiplyAmounts(cost.amount, rate!.rate!);
      amount = difference(row.value, converted);
      percent = returnPercent(amount, converted);
      if (percent === null) reason = "zero_cost";
      knownCosts.push(converted);
      knownReturns.push(amount);
      stale ||= row.stale || (!zeroCost && rate?.status === "stale");
    }
    rows.set(key, { amount, percent, reason });
  }
  const complete = knownReturns.length === valuation.positionCount,
    amount = complete ? sumAmounts(knownReturns) : null,
    cost = complete ? sumAmounts(knownCosts) : null;
  const total: ProfitLoss = {
    amount,
    percent: amount !== null && cost !== null ? returnPercent(amount, cost) : null,
    reason: complete && cost === "0" ? "zero_cost" : null,
  };
  return { rows, total, complete, knownCount: knownReturns.length, stale };
}

export function profitLossLabel(value: string | null, mode: ProfitLossMode, currency: Currency) {
  if (value === null) return "—";
  const n = decimal(value, true).n,
    sign = n < BigInt(0) ? "−" : n > BigInt(0) ? "+" : "",
    magnitude = value.startsWith("-") ? value.slice(1) : value,
    rounded = roundDisplayAmount(magnitude, mode === "percent" ? "USD" : currency),
    tiny = n !== BigInt(0) && !/[1-9]/.test(rounded);
  if (mode === "percent") return `${sign}${tiny ? "<0.01" : rounded}%`;
  return `${sign}${tiny ? `${currency} <${currency === "JPY" ? "1" : "0.01"}` : money(magnitude, currency)}`;
}
export function percentage(value: string, total: string): string | null {
  const a = decimal(value),
    b = decimal(total);
  if (b.n === BigInt(0)) return null;
  const numerator = a.n * BigInt(10) ** BigInt(b.scale + 8),
    denominator = b.n * BigInt(10) ** BigInt(a.scale);
  let n = numerator / denominator;
  const remainder = numerator % denominator;
  if (
    remainder * BigInt(2) > denominator ||
    (remainder * BigInt(2) === denominator && n % BigInt(2) !== BigInt(0))
  )
    n++;
  return plain(n, 6);
}
export function valuePortfolio(
  facts: HoldingsFacts,
  prices: PriceSet,
  currency: Currency,
): HoldingsValuation {
  const natives = facts.data.accounts.flatMap((a) => a.positions.map((p) => p.instrument.currency)),
    fx = displayFx(prices.fx, natives, currency);
  const batches = prices.quotes.map((b) => quoteBatch(b));
  const indexed = new Map<string, number>();
  batches.forEach((b, n) =>
    b.items.forEach((i) => {
      const key = instrumentKey(i.instrument);
      if (indexed.has(key)) throw Error("duplicate_quote");
      indexed.set(key, n);
    }),
  );
  const groups = [...batches, missingQuotes([], prices.fx.fetchedAt)].map((batch, n) => {
    const data = {
      ...facts.data,
      accounts: facts.data.accounts.map((a) => ({
        ...a,
        positions: a.positions.filter(
          (p) => (indexed.get(instrumentKey(p.instrument)) ?? batches.length) === n,
        ),
      })),
    };
    return valueHoldings({ ...facts, data }, batch, fx, currency);
  });
  const rows = groups.flatMap((v) => v.rows),
    known = rows.flatMap((r) => (r.value === null ? [] : [r.value])),
    subtotal = known.length || !rows.length ? sumAmounts(known) : null;
  for (const row of rows)
    row.weightPercent =
      row.value === null || subtotal === null ? null : percentage(row.value, subtotal);
  return {
    currency,
    subtotal,
    complete: rows.every((r) => r.value !== null),
    valuedCount: known.length,
    positionCount: rows.length,
    stale: rows.some((r) => r.stale),
    rows,
    quoteSnapshotIds: batches.map((b) => b.snapshotId),
    fxSnapshotId: fx.snapshotId,
  };
}
export function money(value: string | null, currency: Currency) {
  if (value === null) return "—";
  const [whole, tail] = roundDisplayAmount(value, currency).split(".");
  return `${currency} ${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${tail === undefined ? "" : "." + tail}`;
}
export function unitMoney(value: string | null, currency: Currency) {
  if (value === null) return "—";
  return `${currency} ${decimalLabel(value)}`;
}
export function decimalLabel(value: string) {
  const [whole, tail] = value.split(".");
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${tail === undefined ? "" : "." + tail}`;
}
export function weightLabel(value: string | null | undefined) {
  if (value === null || value === undefined) return "—";
  const rounded = roundDisplayAmount(value, "USD");
  return rounded === "0.00" && /[1-9]/.test(value) ? "<0.01%" : `${rounded.replace(/\.00$/, "")}%`;
}

export type AllocationSlice = {
  key: string;
  label: string;
  detail?: string;
  value: string;
  weight: string;
  positions: number;
};
export function allocation(
  facts: HoldingsFacts,
  valuation: HoldingsValuation,
  othersLabel: string,
): AllocationSlice[] {
  if (!valuation.subtotal || decimal(valuation.subtotal).n === BigInt(0)) return [];
  const labels = new Map(
    facts.data.accounts.flatMap((a) =>
      a.positions.map(
        (p) =>
          [JSON.stringify([a.accountId, p.assetId]), p.instrument.symbol ?? p.name ?? "—"] as const,
      ),
    ),
  );
  const details = new Map(
    facts.data.accounts.flatMap((a) =>
      a.positions.map(
        (p) =>
          [
            JSON.stringify([a.accountId, p.assetId]),
            [
              p.instrument.currency,
              ...(facts.data.accounts.length > 1 ? [a.displayName] : []),
            ].join(" · "),
          ] as const,
      ),
    ),
  );
  const rows: AllocationSlice[] = valuation.rows
    .filter((r) => r.value !== null && decimal(r.value).n > BigInt(0))
    .map((r) => ({
      key: JSON.stringify([r.accountId, r.assetId]),
      label: labels.get(JSON.stringify([r.accountId, r.assetId])) ?? "—",
      detail: details.get(JSON.stringify([r.accountId, r.assetId])),
      value: r.value!,
      weight: r.weightPercent!,
      positions: 1,
    }))
    .sort((a, b) => Number(b.weight) - Number(a.weight));
  if (rows.length <= 12) return rows;
  const rest = rows.splice(11),
    value = sumAmounts(rest.map((r) => r.value));
  rows.push({
    key: "others",
    label: othersLabel,
    value,
    weight: percentage(value, valuation.subtotal)!,
    positions: rest.length,
  });
  return rows;
}

export { readPublicValuation } from "./public-market-json";

export { displayCurrencies, quoteBatch, fxBatch };
export type { Currency, HoldingsFacts, Instrument, Pair, QuoteItem, FxItem, Batch };
