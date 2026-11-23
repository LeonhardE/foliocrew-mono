"use client";
import { useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useCurrencyPreferences } from "./CurrencyPreferencesProvider";
import { useHoldingsValuation } from "./useHoldingsValuation";
import type { HoldingsWorkspace } from "./useHoldingsWorkspace";
import { ReportDialog } from "./ReportDialog";
import { EmptyState, InlineError, LoadingIndicator } from "./WorkspaceFeedback";
import { formatHoldingsTime } from "@/lib/holdings-facts";
import {
  allocation,
  brokerValuation,
  instrumentKey,
  money,
  unitMoney,
  decimalLabel,
  weightLabel,
  sumAmounts,
  valueReportedCash,
  portfolioProfitLoss,
  profitLossLabel,
  type AllocationSlice,
  type Currency,
  type ProfitLoss,
  type ProfitLossMode,
  type HoldingsFacts,
  type HoldingsValuation as Valuation,
} from "@/lib/holdings-valuation";
import styles from "./HoldingsValuation.module.css";

const quoteRefreshErrors = {
  daily: "quoteDailyLimit",
  minute: "quoteMinuteLimit",
  provider: "quoteProviderLimit",
  busy: "quoteRefreshBusy",
  unavailable: "quoteRefreshUnavailable",
} as const;

const COLORS = [
  "#4263c7",
  "#9c60b5",
  "#008c91",
  "#be7936",
  "#5a8d49",
  "#b45179",
  "#7183be",
  "#a29437",
  "#4a8aab",
  "#af6c57",
  "#8074ad",
  "#6e7e84",
];
function Pie({ rows, label }: { rows: AllocationSlice[]; label: string }) {
  let offset = 0;
  return (
    <svg viewBox="0 0 200 200" className={styles.pie} role="img" aria-label={label}>
      {rows.map((row, n) => {
        const part = Math.min(100 - offset, Math.max(0, Number(row.weight))),
          start = (offset * Math.PI) / 50 - Math.PI / 2;
        offset += part;
        const end = (offset * Math.PI) / 50 - Math.PI / 2;
        return part >= 99.999999 ? (
          <circle key={row.key} cx="100" cy="100" r="86" fill={COLORS[n]} />
        ) : (
          <path
            key={row.key}
            fill={COLORS[n]}
            d={`M100 100 L${100 + 86 * Math.cos(start)} ${100 + 86 * Math.sin(start)} A86 86 0 ${part > 50 ? 1 : 0} 1 ${100 + 86 * Math.cos(end)} ${100 + 86 * Math.sin(end)} Z`}
          />
        );
      })}
    </svg>
  );
}
export function HoldingsAllocation({
  facts,
  valuation,
  identity,
  onClose,
}: {
  facts: HoldingsFacts;
  valuation: Valuation;
  identity: string;
  onClose: () => void;
}) {
  const t = useTranslations("holdingsValuation"),
    [kind, setKind] = useState<"pie" | "bar">("pie");
  const rows = useMemo(() => allocation(facts, valuation, t("others")), [facts, valuation, t]);
  return (
    <ReportDialog
      id="holdings-allocation"
      open
      identity={identity}
      title={t("allocation")}
      closeLabel={t("close")}
      onClose={onClose}
    >
      <div className={styles.chartHeader}>
        <strong>{money(valuation.subtotal, valuation.currency)}</strong>
        <div className={styles.segmented} role="group" aria-label={t("chartType")}>
          <button type="button" aria-pressed={kind === "pie"} onClick={() => setKind("pie")}>
            {t("pie")}
          </button>
          <button type="button" aria-pressed={kind === "bar"} onClick={() => setKind("bar")}>
            {t("bar")}
          </button>
        </div>
      </div>
      <p className={styles.note}>
        {t(valuation.complete ? "denominator" : "partialDenominator", {
          known: valuation.valuedCount,
          total: valuation.positionCount,
        })}
      </p>
      {!rows.length ? (
        <EmptyState title={t("emptyChart")} detail={t("emptyChartHelp")} />
      ) : (
        <div key={kind} className={styles.chart} data-kind={kind}>
          {kind === "pie" ? (
            <Pie rows={rows} label={t("allocation")} />
          ) : (
            <div className={styles.bars} role="img" aria-label={t("allocation")}>
              {rows.map((row, n) => (
                <div className={styles.barRow} key={row.key}>
                  <span>{row.label}</span>
                  <span className={styles.track}>
                    <span
                      style={{
                        width: `${Math.min(100, Number(row.weight))}%`,
                        background: COLORS[n],
                      }}
                    />
                  </span>
                </div>
              ))}
            </div>
          )}
          <ul className={styles.legend}>
            {rows.map((row, n) => (
              <li key={row.key}>
                <span
                  className={styles.swatch}
                  style={{ background: COLORS[n] }}
                  aria-hidden="true"
                />
                <span>
                  {row.label}
                  {row.detail && <small>{row.detail}</small>}
                  {row.positions > 1 && <small>{t("grouped", { count: row.positions })}</small>}
                </span>
                <span>
                  <strong>{money(row.value, valuation.currency)}</strong>
                  <small>{weightLabel(row.weight)}</small>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className={styles.note}>{t("cashExcluded")}</p>
    </ReportDialog>
  );
}

export default function HoldingsValuation({
  model,
  onEdit,
  active = true,
}: {
  model: HoldingsWorkspace;
  onEdit?: (accountId: string, assetId: string) => void;
  active?: boolean;
}) {
  const t = useTranslations("holdingsValuation"),
    locale = useLocale(),
    preferences = useCurrencyPreferences();
  const view = useHoldingsValuation(model, preferences.defaultPortfolioCurrency, active);
  const [chart, setChart] = useState<string | null>(null);
  const [profitMode, setProfitMode] = useState<ProfitLossMode>("percent");
  const identity = model.editScope;
  const [valuationSource, setValuationSource] = useState<{
    identity: string;
    source: "market" | "broker";
  } | null>(null);
  const imported = useMemo(
    () =>
      view.facts && view.prices && view.currency
        ? brokerValuation(view.facts, view.prices, view.currency)
        : null,
    [view.facts, view.prices, view.currency],
  );
  const chosenSource =
    valuationSource && valuationSource.identity === identity ? valuationSource.source : null;
  const showBroker = Boolean(
    imported &&
    (chosenSource === "broker" ||
      (!chosenSource && imported.valuedCount > (view.valuation?.valuedCount ?? 0))),
  );
  const valuation = showBroker ? imported : view.valuation;
  const profit = useMemo(
    () =>
      view.facts && valuation && view.prices
        ? portfolioProfitLoss(view.facts, valuation, view.prices)
        : null,
    [view.facts, valuation, view.prices],
  );
  useEffect(() => setChart(null), [identity]);
  const quoteMap = useMemo(
    () =>
      new Map(
        view.prices?.quotes.flatMap((b) =>
          b.items.map((i) => [instrumentKey(i.instrument), i] as const),
        ) ?? [],
      ),
    [view.prices],
  );
  const rows = useMemo(
    () => new Map(valuation?.rows.map((r) => [JSON.stringify([r.accountId, r.assetId]), r]) ?? []),
    [valuation],
  );
  const cash = useMemo(() => {
    const values = new Map<Currency, Array<string | null>>();
    for (const a of view.facts?.data.accounts ?? [])
      for (const b of a.balances)
        values.set(b.currency, [...(values.get(b.currency) ?? []), b.cashBalance]);
    return [...values].map(([currency, amounts]) => {
      const known = amounts.filter((v): v is string => v !== null);
      return {
        currency,
        amount: known.length ? sumAmounts(known) : null,
        complete: known.length === amounts.length,
      };
    });
  }, [view.facts]);
  const cashValuation = useMemo(
    () =>
      view.facts && view.prices && view.currency
        ? valueReportedCash(view.facts, view.prices, view.currency)
        : null,
    [view.facts, view.prices, view.currency],
  );
  if (!view.facts) return null;
  const securitiesAmount = valuation?.subtotal ?? null;
  const summaryAmounts = [securitiesAmount, cashValuation?.subtotal ?? null].filter(
    (amount): amount is string => amount !== null,
  );
  const summaryAmount = summaryAmounts.length ? sumAmounts(summaryAmounts) : null;
  const hasCash = cash.length > 0;
  const partialCashValuation = hasCash && cashValuation?.complete === false;
  const incomplete = Boolean((valuation && !valuation.complete) || partialCashValuation);
  const times = [...quoteMap.values()].flatMap((q) => (q.sourceAsOf ? [q.sourceAsOf] : [])).sort();
  const fxDate = view.prices?.fx.items.find((i) => i.sourceDate)?.sourceDate;
  const showProfit = (value: ProfitLoss | undefined) => {
    const amount = value?.[profitMode] ?? null,
      tone =
        !value?.amount || !/[1-9]/.test(value.amount)
          ? ""
          : value.amount.startsWith("-")
            ? "negative"
            : "positive",
      help =
        value?.reason === "zero_cost"
          ? profitMode === "percent"
            ? "profitZeroCost"
            : null
          : value?.reason === "missing_cost"
            ? "profitMissingCost"
            : value?.reason === "missing_cost_fx"
              ? "profitMissingFx"
              : value?.reason === "missing_value"
                ? "profitMissingValue"
                : null;
    return (
      <span className={styles.profit}>
        <strong className={tone}>
          {view.currency ? profitLossLabel(amount, profitMode, view.currency) : "—"}
        </strong>
        {help && <small>{t(help)}</small>}
      </span>
    );
  };
  return (
    <div className={styles.workspace}>
      <div className={styles.summary}>
        <div>
          <span className={styles.caption}>
            {t(
              hasCash
                ? incomplete
                  ? "subtotalWithCash"
                  : "totalWithCash"
                : incomplete
                  ? "subtotal"
                  : "total",
            )}
          </span>
          <strong className={styles.total}>
            {view.currency ? money(summaryAmount, view.currency) : "—"}
          </strong>
          <div className={styles.summaryProfit}>
            <span className={styles.caption}>{t("profitLoss")}</span>
            {showProfit(profit?.total)}
          </div>
          {profit && !profit.complete && (
            <span className={styles.coverage}>
              {t("profitCoverage", {
                known: profit.knownCount,
                total: valuation!.positionCount,
              })}
            </span>
          )}
          {partialCashValuation && (
            <span className={styles.coverage}>{t("cashValuationPartial")}</span>
          )}
          {valuation && !valuation.complete && (
            <span className={styles.coverage}>
              {t("coverage", {
                known: valuation.valuedCount,
                total: valuation.positionCount,
              })}
            </span>
          )}
        </div>
        <div className={styles.actions}>
          <button type="button" onClick={() => setChart(identity)} disabled={!valuation}>
            {t("visualize")}
          </button>
          <button
            className={styles.refreshButton}
            type="button"
            onClick={view.refresh}
            disabled={view.busy || !view.currency}
          >
            {t("refresh")}
          </button>
        </div>
      </div>
      <div className={styles.displayOptions}>
        {imported && (
          <label className={styles.displayOption}>
            <span className={styles.caption}>{t("valuationSource")}</span>
            <select
              value={showBroker ? "broker" : "market"}
              onChange={(event) =>
                setValuationSource({
                  identity,
                  source: event.target.value === "broker" ? "broker" : "market",
                })
              }
            >
              <option value="market">{t("marketValuation")}</option>
              <option value="broker">{t("brokerValuation")}</option>
            </select>
          </label>
        )}
        <label className={styles.displayOption}>
          <span className={styles.caption}>{t("displayCurrency")}</span>
          <select
            aria-label={t("displayCurrency")}
            value={view.currency ?? ""}
            disabled={!view.currency}
            onChange={(e) => view.select(e.target.value as Currency)}
          >
            {!view.currency && <option value="">—</option>}
            {view.options.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label className={styles.displayOption}>
          <span className={styles.caption}>{t("profitMode")}</span>
          <select
            aria-label={t("profitMode")}
            value={profitMode}
            onChange={(event) =>
              setProfitMode(event.target.value === "amount" ? "amount" : "percent")
            }
          >
            <option value="percent">{t("profitPercent")}</option>
            <option value="amount">{t("profitAmount")}</option>
          </select>
        </label>
        {!view.isDefault && (
          <button className={styles.resetCurrency} type="button" onClick={view.reset}>
            {t("reset")}
          </button>
        )}
      </div>
      {!preferences.loaded && <LoadingIndicator busy label={t("loadingCurrency")} />}
      {preferences.error && (
        <InlineError
          message={t("currencyError")}
          onRetry={preferences.retry}
          retryLabel={t("retry")}
        />
      )}
      <LoadingIndicator
        busy={view.busy}
        hasContent
        label={t(view.progress?.phase === "cache" ? "loadingPrices" : "updating")}
      />
      {view.busy && view.progress && view.progress.total > 0 && (
        <progress
          className={styles.progress}
          aria-label={t(view.progress.phase === "cache" ? "loadingPrices" : "updating")}
          max={view.progress.total}
          value={view.progress.done}
        />
      )}
      {view.error && (
        <InlineError
          message={t(
            view.prices?.quoteLimit ? quoteRefreshErrors[view.prices.quoteLimit] : "refreshError",
          )}
          onRetry={view.refresh}
          retryLabel={t("retry")}
        />
      )}
      {typeof view.updatedQuotes === "number" && (
        <p className={styles.note} role="status">
          {view.updatedQuotes === 0
            ? t("quoteRefreshUnchanged")
            : t("quoteRefreshUpdated", { count: view.updatedQuotes })}
        </p>
      )}
      {showBroker && (
        <p className={styles.note} role="status">
          {view.facts.data.reportDate
            ? t("brokerValuationDated", { date: view.facts.data.reportDate })
            : t("brokerValuationHelp")}
        </p>
      )}
      {showBroker && !view.valuation?.complete && (
        <p className={styles.note}>
          {t("marketCoverage", {
            known: view.valuation?.valuedCount ?? 0,
            total: imported!.positionCount,
          })}
        </p>
      )}
      {(valuation?.stale || profit?.stale || cashValuation?.stale) && (
        <p className={styles.note} role="status">
          {t("stale")}
        </p>
      )}
      {valuation && !valuation.complete && (
        <p className={styles.note}>
          {t("partialDenominator", {
            known: valuation.valuedCount,
            total: valuation.positionCount,
          })}
        </p>
      )}
      {view.facts.data.accounts.map((account) => (
        <section key={account.accountId} className={styles.account}>
          <h3>{account.displayName}</h3>
          {account.positions.length ? (
            <div className={styles.tableScroll} tabIndex={0} role="region" aria-label={t("table")}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>{t("security")}</th>
                    <th>{t("value")}</th>
                    <th>{t("profitLoss")}</th>
                    <th>{t("weight")}</th>
                    <th>{t("quantity")}</th>
                    <th>{t(showBroker ? "brokerQuote" : "quote")}</th>
                    <th>{t("unitCost")}</th>
                    {onEdit && (
                      <th>
                        <span className="sr-only">{t("edit")}</span>
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {account.positions.map((p) => {
                    const row = rows.get(JSON.stringify([account.accountId, p.assetId])),
                      quote = quoteMap.get(instrumentKey(p.instrument)),
                      reportedPrice = p.reportedValues?.unitPrice;
                    return (
                      <tr key={p.assetId}>
                        <td>
                          <strong>{p.instrument.symbol ?? "—"}</strong>
                          <small>{p.name}</small>
                        </td>
                        <td className={styles.number}>
                          <strong>
                            {view.currency ? money(row?.value ?? null, view.currency) : "—"}
                          </strong>
                          {row && row.status !== "valued" && (
                            <small>
                              {t(
                                !showBroker && quote?.status === "unsupported"
                                  ? "quoteUnsupported"
                                  : showBroker && row.status === "missing_quote"
                                    ? "brokerValueMissing"
                                    : row.status,
                              )}
                            </small>
                          )}
                        </td>
                        <td className={styles.number}>
                          {showProfit(
                            profit?.rows.get(JSON.stringify([account.accountId, p.assetId])),
                          )}
                        </td>
                        <td className={styles.number}>{weightLabel(row?.weightPercent)}</td>
                        <td className={styles.number}>{decimalLabel(p.quantity)}</td>
                        <td className={styles.number}>
                          {showBroker ? (
                            unitMoney(
                              reportedPrice?.amount ?? null,
                              reportedPrice?.currency ?? p.instrument.currency,
                            )
                          ) : (
                            <>
                              {unitMoney(quote?.price ?? null, p.instrument.currency)}
                              {quote?.sourceAsOf && (
                                <small>{formatHoldingsTime(quote.sourceAsOf, locale)}</small>
                              )}
                            </>
                          )}
                        </td>
                        <td
                          className={styles.number}
                          aria-label={p.unitCost === null ? t("unknown") : undefined}
                        >
                          {unitMoney(p.unitCost?.amount ?? null, p.instrument.currency)}
                        </td>
                        {onEdit && (
                          <td>
                            <button
                              type="button"
                              className={styles.edit}
                              aria-label={t("editPosition", {
                                symbol: p.instrument.symbol ?? p.name ?? "—",
                              })}
                              onClick={() => onEdit(account.accountId, p.assetId)}
                            >
                              {t("edit")}
                            </button>
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className={styles.note}>{t("emptyAccount")}</p>
          )}
        </section>
      ))}
      {cash.length > 0 && (
        <div className={styles.cash}>
          <span>{t("cash")}</span>
          {cash.map((c) => (
            <strong key={c.currency}>
              {c.amount === null ? `${c.currency} —` : money(c.amount, c.currency)}
              {!c.complete && c.amount !== null && <small>{t("partialCash")}</small>}
            </strong>
          ))}
          <small>{t("cashExcluded")}</small>
        </div>
      )}
      <details className={styles.details}>
        <summary>{t("dataDetails")}</summary>
        <dl>
          <div>
            <dt>{t("holdingsUpdated")}</dt>
            <dd>{formatHoldingsTime(view.facts.fetchedAt, locale)}</dd>
          </div>
          <div>
            <dt>{t("quoteTimes")}</dt>
            <dd>
              {times.length
                ? `${formatHoldingsTime(times[0], locale)}${times[0] !== times.at(-1) ? ` – ${formatHoldingsTime(times.at(-1)!, locale)}` : ""}`
                : "—"}
            </dd>
          </div>
          <div>
            <dt>{t("fxDate")}</dt>
            <dd>{fxDate ?? "—"}</dd>
          </div>
        </dl>
        <p>{t("costHelp")}</p>
        <p>{t("profitHelp")}</p>
        {!showBroker && <p>{t("quoteSource")}</p>}
        {cash.length > 0 && <p>{t("cashHelp")}</p>}
        {fxDate && (
          <p>
            <a
              href="https://www.bankofcanada.ca/rates/exchange/daily-exchange-rates/"
              target="_blank"
              rel="noreferrer"
            >
              {t("fxSource")}
            </a>
          </p>
        )}
        {view.facts.data.excludedAssets.length > 0 && (
          <p>{t("excluded", { count: view.facts.data.excludedAssets.length })}</p>
        )}
      </details>
      {chart === identity && valuation && (
        <HoldingsAllocation
          facts={view.facts}
          valuation={valuation}
          identity={identity}
          onClose={() => setChart(null)}
        />
      )}
    </div>
  );
}
