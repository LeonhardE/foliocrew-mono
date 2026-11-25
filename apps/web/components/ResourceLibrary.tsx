"use client";
import type { ResourceDisplayAccess } from "@/lib/resource-display";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { useResourceLibrary, type ResourceLibraryModel } from "./useResourceLibrary";
import type { ChannelInput, ResourceKind } from "@/lib/resource-library";
import styles from "./ResourceLibrary.module.css";
import type { WatchlistModel } from "./useWatchlist";
import { LoadingIndicator, InlineError } from "./WorkspaceFeedback";
import { useAuth } from "./AuthProvider";
import type { HoldingsPublication } from "@/lib/holdings-publication";

const kinds: ResourceKind[] = ["holdings", "watchlist", "channel_follows"];
const blank: ChannelInput = { name: "", handleOrUrl: "", note: "" };
export type UserListSync = {
  revision: number;
  status: "syncing" | "synced" | "pending";
  retry: () => void;
};
function FollowsEditor({ model, sync }: { model: ResourceLibraryModel; sync?: UserListSync }) {
  const t = useTranslations("resourceLibrary");
  const taskSync = useTranslations("resourceLibrary.followsSync");
  const [draft, setDraft] = useState<ChannelInput>(blank);
  const [editing, setEditing] = useState<string | null>(null);
  const [opened, setOpened] = useState(false);
  const [localError, setLocalError] = useState("");
  const [removing, setRemoving] = useState<string | null>(null);
  const data = model.follows.data;
  const disabled = model.busy || model.follows.loading || model.follows.stale || !data;
  const owner = model.owner;
  const live = useRef(owner);
  live.current = owner;
  const reset = () => {
    setDraft(blank);
    setEditing(null);
    setOpened(false);
    setRemoving(null);
    setLocalError("");
  };
  const inputs = () =>
    data!.items.map(({ name, handleOrUrl, note }) => ({ name, handleOrUrl, note }));
  const save = async () => {
    if (disabled) return;
    const list = inputs();
    if (editing) {
      const index = data!.items.findIndex((item) => item.followId === editing);
      if (index < 0) {
        setLocalError("edited_removed");
        return;
      }
      list[index] = draft;
    } else list.push(draft);
    if ((await model.saveFollows(list)) && live.current === owner) reset();
  };
  const remove = async () => {
    if (disabled || !removing) return;
    const list = inputs().filter((_item, index) => data!.items[index].followId !== removing);
    if ((await model.saveFollows(list)) && live.current === owner) reset();
  };
  return (
    <>
      <details className={styles.note}>
        <summary>{t("aboutFollows")}</summary>
        <p>{t("followsPrivacy")}</p>
      </details>
      {model.follows.loading && (
        <LoadingIndicator busy hasContent={Boolean(data)} label={t("loading")} />
      )}
      {model.follows.error && (
        <Failure code={model.follows.error} retry={() => void model.reload("follows")} />
      )}
      {data && (
        <>
          {sync?.revision === data.revision && (
            <div className={styles.note} role="status">
              <p>{taskSync(sync.status)}</p>
              {sync.status === "pending" && (
                <button type="button" onClick={sync.retry}>
                  {taskSync("retry")}
                </button>
              )}
            </div>
          )}
          {!data.items.length && <p className={styles.empty}>{t("noFollows")}</p>}
          <ul className={styles.list}>
            {data.items.map((item) => (
              <li key={item.followId}>
                <div>
                  <strong>{item.name}</strong>
                  <small>{item.handleOrUrl}</small>
                  {item.note && <p>{item.note}</p>}
                  <small>{t("userProvided")}</small>
                </div>
                <div className={styles.actions}>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => {
                      setEditing(item.followId);
                      setDraft({
                        name: item.name,
                        handleOrUrl: item.handleOrUrl,
                        note: item.note,
                      });
                      setOpened(true);
                      setRemoving(null);
                    }}
                  >
                    {t("edit")}
                  </button>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => {
                      setRemoving(item.followId);
                      setOpened(false);
                    }}
                  >
                    {t("remove")}
                  </button>
                </div>
              </li>
            ))}
          </ul>
          <p className={styles.note}>
            {t("followCount", { count: data.items.length, limit: data.limit })}
          </p>
          {!opened && !removing && (
            <button
              type="button"
              className={styles.primary}
              disabled={disabled || data.items.length >= data.limit}
              onClick={() => {
                setDraft(blank);
                setEditing(null);
                setOpened(true);
              }}
            >
              {t("addFollow")}
            </button>
          )}
          {opened && (
            <form
              className={styles.form}
              onSubmit={(event) => {
                event.preventDefault();
                void save();
              }}
            >
              <h3>{t(editing ? "editFollow" : "addFollow")}</h3>
              <label>
                {t("name")}
                <input
                  required
                  maxLength={120}
                  value={draft.name}
                  disabled={model.busy}
                  onChange={(event) =>
                    setDraft((previous) => ({ ...previous, name: event.target.value }))
                  }
                />
              </label>
              <label>
                {t("locator")}
                <input
                  required
                  maxLength={256}
                  value={draft.handleOrUrl}
                  placeholder="@channel"
                  disabled={model.busy}
                  onChange={(event) =>
                    setDraft((previous) => ({ ...previous, handleOrUrl: event.target.value }))
                  }
                />
              </label>
              <p className={styles.note}>{t("locatorHelp")}</p>
              <label>
                {t("note")}
                <textarea
                  maxLength={1000}
                  rows={3}
                  value={draft.note}
                  disabled={model.busy}
                  onChange={(event) =>
                    setDraft((previous) => ({ ...previous, note: event.target.value }))
                  }
                />
              </label>
              <div className={styles.actions}>
                <button type="submit" className={styles.primary} disabled={disabled}>
                  {t(model.busy ? "saving" : "save")}
                </button>
                <button type="button" disabled={model.busy} onClick={reset}>
                  {t("cancel")}
                </button>
              </div>
            </form>
          )}
          {removing && (
            <div className={styles.warning} role="group" aria-label={t("confirmRemove")}>
              <p>{t("confirmRemove")}</p>
              <div className={styles.actions}>
                <button type="button" disabled={disabled} onClick={() => void remove()}>
                  {t("remove")}
                </button>
                <button type="button" disabled={model.busy} onClick={reset}>
                  {t("cancel")}
                </button>
              </div>
            </div>
          )}
          {localError && (
            <p role="alert" className={styles.warning}>
              {t(`errors.${localError}`)}
            </p>
          )}
          {model.writeError && (
            <p role="alert" className={styles.warning}>
              {t(`errors.${model.writeError}`)}
            </p>
          )}
          {model.follows.stale && model.writeError && (
            <div className={styles.warning}>
              <p>{t("reloadBeforeWrite")}</p>
              <button
                type="button"
                disabled={model.busy}
                onClick={() => void model.reload("follows")}
              >
                {t("reloadLatest")}
              </button>
            </div>
          )}
        </>
      )}
    </>
  );
}
function Failure({ code, retry }: { code: string; retry: () => void }) {
  const t = useTranslations("resourceLibrary");
  return (
    <div className={styles.warning} role="alert">
      <p>{t(`errors.${code}`)}</p>
      <button type="button" onClick={retry}>
        {t("retry")}
      </button>
    </div>
  );
}
export function ResourceLibraryView({
  model,
  children,
  onOpenWatchlist,
  watchlist: sharedWatchlist,
  filter: selectedFilter,
  onFilterChange,
  followsSync,
  watchlistSync,
}: {
  model: ResourceLibraryModel;
  watchlist?: WatchlistModel;
  children: ReactNode | ((model: ResourceLibraryModel) => ReactNode);
  onOpenWatchlist?: () => void;
  filter?: ResourceKind;
  onFilterChange?: (kind: ResourceKind) => void;
  followsSync?: UserListSync;
  watchlistSync?: UserListSync;
}) {
  const t = useTranslations("resourceLibrary");
  const watchlistSyncText = useTranslations("resourceLibrary.watchlistSync");
  const [localFilter, setLocalFilter] = useState<ResourceKind>("holdings");
  const filter = selectedFilter ?? localFilter;
  const setFilter = (kind: ResourceKind) => {
    if (selectedFilter === undefined) setLocalFilter(kind);
    onFilterChange?.(kind);
  };
  const [symbol, setSymbol] = useState("");
  const shared = sharedWatchlist?.sessionKey === model.owner ? sharedWatchlist : null;
  const pendingWatchlistOwner = useRef<string | null>(null);
  useEffect(() => {
    if (!model.owner || shared?.sessionKey !== model.owner) {
      pendingWatchlistOwner.current = null;
    } else if (model.offline) {
      pendingWatchlistOwner.current = model.owner;
    } else if (
      pendingWatchlistOwner.current === model.owner &&
      filter === "watchlist" &&
      model.canRefresh &&
      !shared.busy
    ) {
      pendingWatchlistOwner.current = null;
      void shared.reload();
    }
  }, [model.owner, model.offline, model.canRefresh, shared, filter]);
  const sharedHasData = shared && (shared.loaded || shared.items.length > 0);
  const watchlist = sharedWatchlist
    ? {
        data: sharedHasData ? { items: shared.items, limit: shared.limit } : null,
        loading: !model.offline && (!shared || shared.loading),
        error: model.offline && !sharedHasData ? "unavailable" : (shared?.error ?? ""),
        stale: Boolean(sharedHasData && (model.offline || shared.error)),
      }
    : model.watchlist;
  const canEditWatchlist =
    shared?.loaded &&
    !shared.busy &&
    !shared.error &&
    !model.offline &&
    pendingWatchlistOwner.current !== shared.sessionKey;
  const retryWatchlist = () => {
    if (model.offline) return;
    if (sharedWatchlist) void shared?.reload();
    else void model.reload("watchlist");
  };
  const submitWatchlist = (event: React.FormEvent) => {
    event.preventDefault();
    if (canEditWatchlist && symbol.trim()) {
      void shared.add(symbol.trim().toUpperCase());
      setSymbol("");
    }
  };
  return (
    <div className={styles.library}>
      {(model.catalogue.stale ||
        (filter === "channel_follows" && model.follows.stale) ||
        (filter === "watchlist" && watchlist.stale)) && (
        <div className={styles.warning} role="status">
          <p>{t("cachedData")}</p>
          <button
            type="button"
            disabled={model.busy || model.offline}
            onClick={() => {
              if (model.catalogue.stale) void model.reload("catalogue");
              if (filter === "channel_follows" && model.follows.stale) void model.reload("follows");
              if (filter === "watchlist" && watchlist.stale) retryWatchlist();
            }}
          >
            {t("retry")}
          </button>
        </div>
      )}
      {model.catalogue.stale && model.catalogue.error && (
        <InlineError
          message={t("taskUnavailable")}
          retryLabel={t("retry")}
          onRetry={() => void model.reload("catalogue")}
        />
      )}
      <div className={styles.filters} role="group" aria-label={t("filterLabel")}>
        {kinds.map((kind) => (
          <button
            type="button"
            key={kind}
            aria-pressed={filter === kind}
            onClick={() => setFilter(kind)}
          >
            {t(`kinds.${kind}`)}
          </button>
        ))}
      </div>
      {filter === "holdings" && (
        <section className={styles.section} aria-label={t("kinds.holdings")}>
          {typeof children === "function" ? children(model) : children}
        </section>
      )}
      {filter === "watchlist" && (
        <section className={styles.section} aria-labelledby="watchlist-library-title">
          <div className={styles.heading}>
            <div>
              <h2 id="watchlist-library-title">{t("kinds.watchlist")}</h2>
            </div>
            {!sharedWatchlist && onOpenWatchlist && (
              <button type="button" onClick={onOpenWatchlist}>
                {t("manageInMarket")} ↗
              </button>
            )}
          </div>
          {shared && (
            <form className={styles.addSymbol} onSubmit={submitWatchlist}>
              <label>
                <span className="sr-only">{t("symbolLabel")}</span>
                <input
                  aria-label={t("symbolLabel")}
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value)}
                  maxLength={20}
                  placeholder={t("symbolPlaceholder")}
                  disabled={!canEditWatchlist}
                />
              </label>
              <button type="submit" disabled={!canEditWatchlist || !symbol.trim()}>
                {t("addStock")}
              </button>
            </form>
          )}
          {!model.authenticated && <p className={styles.empty}>{t("signInLists")}</p>}
          {model.authenticated && watchlist.loading && (
            <LoadingIndicator busy hasContent={Boolean(watchlist.data)} label={t("loading")} />
          )}
          {model.authenticated && watchlist.error && (
            <Failure
              code={sharedWatchlist ? "unavailable" : watchlist.error}
              retry={retryWatchlist}
            />
          )}
          {model.authenticated && watchlist.data && (
            <>
              {watchlistSync && watchlistSync.revision === sharedWatchlist?.revision && (
                <div className={styles.note} role="status">
                  <p>{watchlistSyncText(watchlistSync.status)}</p>
                  {watchlistSync.status === "pending" && (
                    <button type="button" onClick={watchlistSync.retry}>
                      {watchlistSyncText("retry")}
                    </button>
                  )}
                </div>
              )}
              {!watchlist.data.items.length && <p className={styles.empty}>{t("noWatchlist")}</p>}
              <ul className={styles.watchlistRows} data-editable={Boolean(shared)}>
                {watchlist.data.items.map((item) => (
                  <li key={item.symbol}>
                    <strong>{item.symbol}</strong>
                    <span>{item.name}</span>
                    <small>{t(`instruments.${item.instrumentType}`)}</small>
                    {shared && (
                      <button
                        type="button"
                        disabled={!canEditWatchlist}
                        aria-label={t("removeStock", { symbol: item.symbol })}
                        onClick={() => void shared.remove(item.symbol)}
                      >
                        {t("remove")}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}
      {filter === "channel_follows" && (
        <section className={styles.section} aria-labelledby="follows-library-title">
          <div className={styles.heading}>
            <div>
              <h2 id="follows-library-title">{t("kinds.channel_follows")}</h2>
              <p>{t("manualOnly")}</p>
            </div>
          </div>
          {!model.authenticated ? (
            <p className={styles.empty}>{t("signInLists")}</p>
          ) : (
            <FollowsEditor key={model.owner} model={model} sync={followsSync} />
          )}
        </section>
      )}
    </div>
  );
}
export default function ResourceLibrary({
  active = true,
  holdingsVersion,
  watchlist,
  workspaceScope,
  holdingsPublication,
  holdingsCatalogueNeeded = true,
  resumeCatalogueOnNavigation = false,
  resourceDisplay,
  beforeSaveFollows,
  onSavedFollows,
  ...props
}: {
  active?: boolean;
  workspaceScope?: string | null;
  holdingsVersion?: string;
  holdingsPublication?: HoldingsPublication | null;
  holdingsCatalogueNeeded?: boolean;
  resumeCatalogueOnNavigation?: boolean;
  resourceDisplay?: ResourceDisplayAccess;
  watchlist?: WatchlistModel;
  children: ReactNode | ((model: ResourceLibraryModel) => ReactNode);
  onOpenWatchlist?: () => void;
  beforeSaveFollows?: (revision: number, owner: string) => Promise<void>;
  onSavedFollows?: (revision: number, owner: string) => void;
  followsSync?: UserListSync;
  watchlistSync?: UserListSync;
}) {
  const auth = useAuth();
  const owner = auth.status === "authenticated" && auth.profile ? auth.sessionKey : null;
  const [selection, setSelection] = useState<{ owner: string | null; kind: ResourceKind }>({
    owner,
    kind: "holdings",
  });
  const filter = selection.owner === owner ? selection.kind : "holdings";
  useEffect(() => {
    if (selection.owner !== owner) setSelection({ owner, kind: "holdings" });
  }, [owner, selection.owner]);
  const model = useResourceLibrary({
    active,
    workspaceScope,
    externalWatchlist: Boolean(watchlist),
    followsNeeded: filter === "channel_follows",
    catalogueNeeded: filter === "holdings" && holdingsCatalogueNeeded,
    resumeCatalogueOnNavigation,
    resourceDisplay,
    holdingsPublication,
    beforeSaveFollows,
    onSavedFollows,
  });
  const previousVersion = useRef(holdingsVersion);
  useEffect(() => {
    // Opening a snapshot temporarily clears decrypted content. That gap does not
    // change the resource; Owner, vault and source epochs already reset its scope.
    // Invalidate only when a different verified snapshot has been published.
    if (holdingsVersion === undefined) return;
    if (previousVersion.current !== holdingsVersion) {
      previousVersion.current = holdingsVersion;
      if (model.publicationBound) return;
      if (active && model.authenticated && model.configured) void model.reload("catalogue");
    }
  }, [
    holdingsVersion,
    active,
    model.authenticated,
    model.configured,
    model.reload,
    model.publicationBound,
  ]);
  return (
    <ResourceLibraryView
      key={model.owner ?? "guest"}
      model={model}
      filter={filter}
      onFilterChange={(kind) => setSelection({ owner, kind })}
      watchlist={watchlist}
      {...props}
    />
  );
}
