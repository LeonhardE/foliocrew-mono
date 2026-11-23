"use client";
import {
  RESOURCE_DISPLAY_PATH,
  type ResourceDisplayAccess,
  type ResourceDisplayContext,
} from "@/lib/resource-display";
import { hasFreshWorkspaceDisplay, untilSignal } from "@/lib/workspace-cache";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import {
  channelInputs,
  readChannelFollows,
  readResourceCatalogue,
  readResourceWatchlist,
  ResourceError,
  resourceSelection,
  RESOURCE_CONTRACT,
  type ChannelInput,
  type ChannelFollows,
  type ResourceCatalogue,
  type ResourceItem,
  type ResourceLoad,
  type ResourceSelection,
} from "@/lib/resource-library";
import type { WatchlistResponse } from "@/lib/watchlist";
import {
  bindHoldingsPublication,
  catalogueHasPublishedHoldings,
  sameHoldingsPublication,
  type HoldingsPublication,
} from "@/lib/holdings-publication";

type Source = "catalogue" | "watchlist" | "follows";
type CatalogueOutcome = { scope: string | null; serial: number } & (
  { status: "loaded"; data: ResourceCatalogue; at: number } | { status: "failed" | "cancelled" }
);
type Publication = {
  scope: string | null;
  value: HoldingsPublication;
  confirmed: boolean;
  force: boolean;
};
type State = {
  owner: string | null;
  scope: string | null;
  catalogue: ResourceLoad<ResourceCatalogue>;
  watchlist: ResourceLoad<WatchlistResponse>;
  follows: ResourceLoad<ChannelFollows>;
  busy: boolean;
  writeError: string;
};
const empty = <T>(): ResourceLoad<T> => ({ data: null, loading: false, error: "", stale: false });
const initial = (owner: string | null, scope: string | null): State => ({
  owner,
  scope,
  catalogue: empty(),
  watchlist: empty(),
  follows: empty(),
  busy: false,
  writeError: "",
});
const browserOnline = () => typeof navigator === "undefined" || navigator.onLine !== false;
const errorCode = (error: unknown) => (error instanceof ResourceError ? error.code : "unavailable");
const selectionKey = (item: ResourceItem) => {
  const selection = resourceSelection(item);
  return selection
    ? JSON.stringify([
        selection.ref.kind,
        selection.ref.sourceService,
        selection.ref.resourceId,
        selection.ref.incarnation,
        selection.sourceEpoch,
      ])
    : null;
};

/** Source lists use their existing User owner API; discovery never grants agent access. */
export function useResourceLibrary({
  active = true,
  externalWatchlist = false,
  followsNeeded = true,
  catalogueNeeded = true,
  resumeCatalogueOnNavigation = false,
  resourceDisplay,
  workspaceScope = null,
  holdingsPublication = null,
}: {
  active?: boolean;
  externalWatchlist?: boolean;
  followsNeeded?: boolean;
  catalogueNeeded?: boolean;
  resumeCatalogueOnNavigation?: boolean;
  resourceDisplay?: ResourceDisplayAccess;
  workspaceScope?: string | null;
  holdingsPublication?: HoldingsPublication | null;
} = {}) {
  const auth = useAuth();
  const owner = auth.status === "authenticated" && auth.profile ? auth.sessionKey : null;
  const configured = auth.agentHubConfigured;
  const scope = owner ? JSON.stringify([owner, workspaceScope]) : null;
  const [documentVisible, setDocumentVisible] = useState(
    () => typeof document === "undefined" || document.visibilityState !== "hidden",
  );
  const [online, setOnline] = useState(browserOnline);
  const foreground = documentVisible && online;
  const [state, setState] = useState<State>(() => initial(owner, scope));
  const stateRef = useRef(state);
  stateRef.current = state;
  const live = useRef({
    owner,
    scope,
    configured,
    active,
    foreground,
    catalogueNeeded,
    resumeCatalogueOnNavigation,
    resourceDisplay,
  });
  live.current = {
    owner,
    scope,
    configured,
    active,
    foreground,
    catalogueNeeded,
    resumeCatalogueOnNavigation,
    resourceDisplay,
  };
  const tabReturn = useRef(false);
  const jobs = useRef(new Map<string, AbortController>());
  const serials = useRef({ catalogue: 0, watchlist: 0, follows: 0 });
  const writing = useRef<object | null>(null);
  const freshness = useRef<{ scope: string | null; at: Partial<Record<Source, number>> }>({
    scope,
    at: {},
  });
  const catalogueRead = useRef<{
    scope: string | null;
    serial: number;
    canResume: boolean;
    pending: boolean;
    promise: Promise<CatalogueOutcome>;
    outcome?: CatalogueOutcome;
  } | null>(null);
  const catalogueSnapshot = useRef<Extract<CatalogueOutcome, { status: "loaded" }> | null>(null);
  const publication = useRef<Publication | null>(null);
  const previousPublication = useRef<{ scope: string | null; value: HoldingsPublication | null }>({
    scope,
    value: null,
  });
  if (previousPublication.current.scope !== scope)
    previousPublication.current = { scope, value: null };
  const bound = bindHoldingsPublication(holdingsPublication, owner, workspaceScope);
  if (!bound) {
    if (documentVisible || publication.current?.scope !== scope) publication.current = null;
  } else if (
    publication.current?.scope !== scope ||
    !sameHoldingsPublication(publication.current.value, bound)
  ) {
    publication.current = {
      scope,
      value: bound,
      confirmed: false,
      force: Boolean(
        previousPublication.current.value &&
        !sameHoldingsPublication(previousPublication.current.value, bound),
      ),
    };
    previousPublication.current.value = bound;
  }
  const currentPublication = publication.current;
  const verifiedAt = (source: Source) =>
    freshness.current.scope === scope ? freshness.current.at[source] : undefined;
  // Age governs reuse on reentry, not the validity of an uninterrupted, verified view.
  const isFresh = (source: Source) => {
    const at = verifiedAt(source);
    const age = at === undefined ? Infinity : Date.now() - at;
    return age >= 0 && age < 30_000;
  };

  const operation = useCallback(
    async <T>(
      key: string,
      hub: boolean,
      action: (signal: AbortSignal, assert: () => void) => Promise<T>,
      finishAfterNavigation = false,
    ): Promise<T> => {
      const start = live.current;
      if (
        !owner ||
        start.owner !== owner ||
        start.scope !== scope ||
        !start.active ||
        !start.foreground ||
        (hub && !start.configured) ||
        (key === "catalogue" && !start.catalogueNeeded)
      )
        throw new ResourceError("cancelled");
      jobs.current.get(key)?.abort();
      const controller = new AbortController();
      jobs.current.set(key, controller);
      let timeout = false;
      const timer = window.setTimeout(() => {
        timeout = true;
        controller.abort();
      }, 20_000);
      const assert = () => {
        const now = live.current;
        if (timeout) throw new ResourceError("timeout");
        if (
          controller.signal.aborted ||
          now.owner !== owner ||
          now.scope !== scope ||
          (!now.active &&
            (!finishAfterNavigation ||
              !now.resumeCatalogueOnNavigation ||
              Boolean(publication.current && !publication.current.confirmed))) ||
          !now.foreground ||
          (hub && !now.configured) ||
          (key === "catalogue" &&
            (!now.catalogueNeeded ||
              now.resourceDisplay?.readKey !== start.resourceDisplay?.readKey))
        )
          throw new ResourceError("cancelled");
      };
      try {
        assert();
        const result = await untilSignal(
          action(controller.signal, assert),
          controller.signal,
          () => new ResourceError(timeout ? "timeout" : "cancelled"),
        );
        assert();
        return result;
      } catch (error) {
        assert();
        throw error;
      } finally {
        window.clearTimeout(timer);
        if (jobs.current.get(key) === controller) jobs.current.delete(key);
      }
    },
    [owner, scope],
  );

  const api = useCallback(
    async (
      source: Source,
      signal: AbortSignal,
      assertScope: () => void,
      json?: unknown,
      display?: ResourceDisplayContext,
    ) => {
      const assert = () => {
        assertScope();
        try {
          display?.assertCurrent();
        } catch {
          throw new ResourceError("cancelled");
        }
      };
      assert();
      const response = await auth.requestPrivate(
        source === "catalogue" ? "agent-hub" : "user",
        display
          ? RESOURCE_DISPLAY_PATH
          : source === "catalogue"
            ? "/api/v2/resources/catalogue"
            : source === "watchlist"
              ? "/api/v1/watchlist"
              : "/api/v1/channel-follows",
        owner!,
        {
          method: json === undefined ? "GET" : "PUT",
          signal,
          coalesceDisplay: json === undefined,
          ...(display ? { coalesceDisplayScope: display.coalesceScope } : {}),
          ...(json === undefined ? {} : { json }),
          ...(source === "catalogue"
            ? { headers: { "X-FolioView-Contract": RESOURCE_CONTRACT } }
            : {}),
        },
      );
      assert();
      if (!response.ok)
        throw new ResourceError(
          response.status === 409
            ? "conflict"
            : response.status === 403
              ? "forbidden"
              : response.status === 429
                ? "rate_limited"
                : "unavailable",
        );
      if (display && response.status !== 200) throw new ResourceError("invalid_response");
      if (
        !response.body ||
        response.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() !==
          "application/json"
      )
        throw new ResourceError("invalid_response");
      const reader = response.body.getReader(),
        decoder = new TextDecoder("utf-8", { fatal: true });
      const cancel = () => {
        void reader.cancel().catch(() => {});
      };
      signal.addEventListener("abort", cancel, { once: true });
      let size = 0,
        text = "";
      try {
        for (;;) {
          const part = await untilSignal(
            reader.read(),
            signal,
            () => new ResourceError("cancelled"),
          );
          assert();
          if (part.done) break;
          size += part.value.byteLength;
          if (size > (source === "catalogue" ? 1048576 : source === "follows" ? 196608 : 131072))
            throw new ResourceError("invalid_response");
          text += decoder.decode(part.value, { stream: true });
        }
        text += decoder.decode();
        assert();
        const value: unknown = JSON.parse(text);
        if (display) {
          const data = display.read(value);
          if (data.mode === "full") return data.catalogue;
          return api(source, signal, assert);
        }
        return source === "catalogue"
          ? readResourceCatalogue(value)
          : source === "watchlist"
            ? readResourceWatchlist(value)
            : readChannelFollows(value);
      } catch (error) {
        if (error instanceof ResourceError) throw error;
        throw new ResourceError("invalid_response");
      } finally {
        signal.removeEventListener("abort", cancel);
        cancel();
        try {
          reader.releaseLock();
        } catch {
          /* Cancelled reader may still be pending. */
        }
      }
    },
    [auth.requestPrivate, owner],
  );

  const reload = useCallback(
    async (source: Source, force = true) => {
      if (
        !owner ||
        live.current.scope !== scope ||
        !live.current.active ||
        !live.current.foreground ||
        (!force &&
          !stateRef.current[source].stale &&
          (isFresh(source) ||
            (tabReturn.current && hasFreshWorkspaceDisplay(verifiedAt(source), Date.now())))) ||
        (source === "follows" && writing.current) ||
        (source === "catalogue" &&
          (!configured ||
            !live.current.catalogueNeeded ||
            (!force &&
              catalogueRead.current?.pending &&
              catalogueRead.current.scope === scope &&
              catalogueRead.current.serial === serials.current.catalogue)))
      )
        return;
      const display =
        source === "catalogue" && !force ? live.current.resourceDisplay?.prepare() : null;
      const canResume =
        source === "catalogue" && !force && !display && live.current.resumeCatalogueOnNavigation;
      const readKey = live.current.resourceDisplay?.readKey;
      const serial = ++serials.current[source];
      let finishCatalogue: ((outcome: CatalogueOutcome) => void) | undefined;
      let outcome: CatalogueOutcome = { scope, serial, status: "cancelled" };
      if (source === "catalogue") {
        const promise = new Promise<CatalogueOutcome>((resolve) => {
          finishCatalogue = resolve;
        });
        catalogueRead.current = { scope, serial, canResume, pending: true, promise };
      }
      const current = () =>
        live.current.owner === owner &&
        live.current.scope === scope &&
        serials.current[source] === serial &&
        (source !== "catalogue" ||
          (live.current.configured &&
            live.current.catalogueNeeded &&
            live.current.resourceDisplay?.readKey === readKey));
      setState((previous) => ({
        ...(previous.scope === scope ? previous : initial(owner, scope)),
        [source]: {
          ...(previous.scope === scope ? previous[source] : empty()),
          loading: true,
          error: "",
          stale: previous.scope === scope && previous[source].stale,
        },
      }));
      try {
        const data = await operation(
          source,
          source === "catalogue",
          (signal, assert) => api(source, signal, assert, undefined, display ?? undefined),
          canResume,
        );
        if (current()) {
          const at = Date.now(),
            required = source === "catalogue" ? publication.current : null;
          // A replacement read must also confirm the still-pending publication,
          // even if the observer waiting on its cancelled predecessor has exited.
          const matches =
            !required ||
            required.scope !== scope ||
            required.confirmed ||
            catalogueHasPublishedHoldings(data as ResourceCatalogue, required.value);
          if (matches) {
            freshness.current.at[source] = at;
            if (required?.scope === scope) required.confirmed = true;
          } else delete freshness.current.at.catalogue;
          if (source === "catalogue") {
            // Keep the verified DTO receipt private from mutable view-model consumers.
            outcome = {
              scope,
              serial,
              status: "loaded",
              data: structuredClone(data as ResourceCatalogue),
              at,
            };
            catalogueSnapshot.current = outcome;
          }
          setState((previous) => ({
            ...previous,
            [source]: {
              data,
              loading: false,
              error: matches ? "" : "reload_required",
              stale: !matches,
            },
            ...(source === "follows" ? { writeError: "" } : {}),
          }));
        }
      } catch (error) {
        outcome = {
          scope,
          serial,
          status: errorCode(error) === "cancelled" ? "cancelled" : "failed",
        };
        if (current() && errorCode(error) !== "cancelled") {
          delete freshness.current.at[source];
          setState((previous) => ({
            ...previous,
            [source]: {
              ...previous[source],
              loading: false,
              stale: Boolean(previous[source].data),
              error: errorCode(error),
            },
          }));
        }
      } finally {
        if (
          source === "catalogue" &&
          catalogueRead.current?.serial === serial &&
          catalogueRead.current.scope === scope
        ) {
          catalogueRead.current.pending = false;
          catalogueRead.current.outcome = outcome;
        }
        finishCatalogue?.(outcome);
      }
    },
    [owner, scope, configured, operation, api],
  );

  const saveFollows = useCallback(
    async (inputs: ChannelInput[]): Promise<boolean> => {
      const before = stateRef.current;
      if (
        !owner ||
        live.current.owner !== owner ||
        before.owner !== owner ||
        before.scope !== scope ||
        live.current.scope !== scope ||
        !live.current.active ||
        !live.current.foreground ||
        verifiedAt("follows") === undefined ||
        jobs.current.has("follows") ||
        !before.follows.data ||
        before.follows.stale ||
        before.follows.loading ||
        writing.current
      )
        return false;
      let items: ChannelInput[];
      try {
        items = channelInputs(inputs);
      } catch (error) {
        setState((previous) => ({ ...previous, writeError: errorCode(error) }));
        return false;
      }
      const token = {};
      writing.current = token;
      ++serials.current.follows;
      ++serials.current.catalogue;
      delete freshness.current.at.catalogue;
      jobs.current.get("follows")?.abort();
      jobs.current.get("catalogue")?.abort();
      setState((previous) => ({
        ...previous,
        busy: true,
        writeError: "",
        catalogue: {
          ...previous.catalogue,
          loading: false,
          stale: Boolean(previous.catalogue.data),
        },
      }));
      try {
        const data = (await operation("write", false, (signal, assert) =>
          api("follows", signal, assert, {
            expectedRevision: before.follows.data!.revision,
            items,
          }),
        )) as ChannelFollows;
        if (
          live.current.owner !== owner ||
          live.current.scope !== scope ||
          writing.current !== token
        )
          return false;
        freshness.current.at.follows = Date.now();
        setState((previous) => ({
          ...previous,
          follows: { data, loading: false, error: "", stale: false },
          busy: false,
          writeError: "",
        }));
        void reload("catalogue");
        return true;
      } catch (error) {
        if (freshness.current.scope === scope) delete freshness.current.at.follows;
        if (
          live.current.owner === owner &&
          live.current.scope === scope &&
          writing.current === token
        )
          setState((previous) => ({
            ...previous,
            follows: { ...previous.follows, stale: true },
            busy: false,
            writeError: errorCode(error) === "cancelled" ? "reload_required" : errorCode(error),
          }));
        return false;
      } finally {
        if (writing.current === token) writing.current = null;
      }
    },
    [owner, scope, api, operation, reload],
  );

  useEffect(() => {
    const visibility = () => {
      const visible = document.visibilityState !== "hidden";
      tabReturn.current = visible && live.current.active;
      setDocumentVisible(visible);
    };
    const connectivity = () => {
      const connected = browserOnline();
      if (!connected) freshness.current.at = {};
      setOnline(connected);
    };
    document.addEventListener("visibilitychange", visibility);
    window.addEventListener?.("offline", connectivity);
    window.addEventListener?.("online", connectivity);
    return () => {
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener?.("offline", connectivity);
      window.removeEventListener?.("online", connectivity);
    };
  }, []);
  useEffect(() => {
    const uncertainWrite = Boolean(writing.current);
    writing.current = null;
    if (!active) tabReturn.current = false;
    if (freshness.current.scope !== scope) {
      tabReturn.current = false;
      freshness.current = { scope, at: {} };
      catalogueRead.current = null;
      catalogueSnapshot.current = null;
    }
    if (!configured) delete freshness.current.at.catalogue;
    if (uncertainWrite) {
      delete freshness.current.at.follows;
      delete freshness.current.at.catalogue;
    }
    ++serials.current.watchlist;
    ++serials.current.follows;
    setState((previous) =>
      previous.scope === scope
        ? {
            ...previous,
            busy: false,
            catalogue: {
              ...previous.catalogue,
              stale: Boolean(previous.catalogue.data && (previous.catalogue.stale || !configured)),
            },
            watchlist: { ...previous.watchlist, loading: false },
            follows: {
              ...previous.follows,
              loading: false,
              ...(uncertainWrite ? { stale: true } : {}),
            },
            ...(uncertainWrite
              ? {
                  writeError: "reload_required",
                  catalogue: {
                    ...previous.catalogue,
                    loading: false,
                    stale: Boolean(previous.catalogue.data),
                  },
                }
              : {}),
          }
        : initial(owner, scope),
    );
    if (owner && active && foreground) {
      if (!externalWatchlist) void reload("watchlist", false);
    }
    return () => {
      for (const [key, controller] of jobs.current) {
        if (key === "catalogue") continue;
        controller.abort();
        jobs.current.delete(key);
      }
    };
  }, [owner, scope, active, foreground, configured, reload, externalWatchlist]);
  const cancelCatalogue = useCallback(() => {
    const controller = jobs.current.get("catalogue");
    if (!controller && !catalogueRead.current?.pending) return;
    controller?.abort();
    ++serials.current.catalogue;
    if (live.current.scope === scope)
      setState((previous) =>
        previous.scope === scope
          ? { ...previous, catalogue: { ...previous.catalogue, loading: false } }
          : previous,
      );
  }, [scope]);
  // An automatic request already sent may finish across same-document navigation.
  // Changes to its authority, demand or document visibility still cancel it.
  useEffect(
    () => cancelCatalogue,
    [
      cancelCatalogue,
      foreground,
      configured,
      catalogueNeeded,
      resourceDisplay?.readKey,
      resumeCatalogueOnNavigation,
      reload,
    ],
  );
  useEffect(() => {
    if (
      !active &&
      catalogueRead.current?.pending &&
      (!catalogueRead.current.canResume || (currentPublication && !currentPublication.confirmed))
    )
      cancelCatalogue();
  }, [active, currentPublication, cancelCatalogue]);
  useEffect(() => {
    if (owner && active && foreground && configured && catalogueNeeded && !writing.current)
      void reload("catalogue", false);
  }, [
    owner,
    active,
    foreground,
    configured,
    catalogueNeeded,
    resourceDisplay?.readKey,
    resumeCatalogueOnNavigation,
    reload,
  ]);
  useEffect(() => {
    if (owner && active && foreground && followsNeeded) void reload("follows", false);
    return () => {
      jobs.current.get("follows")?.abort();
      ++serials.current.follows;
      if (live.current.scope === scope)
        setState((previous) =>
          previous.scope === scope
            ? { ...previous, follows: { ...previous.follows, loading: false } }
            : previous,
        );
    };
  }, [owner, scope, active, foreground, followsNeeded, reload]);

  useEffect(() => {
    const required = currentPublication;
    if (
      !required ||
      !owner ||
      !active ||
      !foreground ||
      !configured ||
      !catalogueNeeded ||
      writing.current
    )
      return;
    let stopped = false;
    const current = () =>
      !stopped &&
      publication.current === required &&
      live.current.owner === owner &&
      live.current.scope === scope &&
      live.current.active &&
      live.current.foreground &&
      live.current.configured &&
      live.current.catalogueNeeded;
    const confirm = async () => {
      if (!current() || required.confirmed) return;
      if (required.force) {
        required.force = false;
        void reload("catalogue");
        return;
      }
      const snapshot = catalogueSnapshot.current;
      if (
        snapshot?.scope === scope &&
        snapshot.serial === serials.current.catalogue &&
        isFresh("catalogue") &&
        catalogueHasPublishedHoldings(snapshot.data, required.value)
      ) {
        required.confirmed = true;
        setState((previous) => ({ ...previous }));
        return;
      }
      const read = catalogueRead.current;
      // Completed failures keep their existing explicit retry; they are not hints.
      if (
        read?.scope === scope &&
        read.serial === serials.current.catalogue &&
        !read.pending &&
        read.outcome?.status !== "loaded"
      )
        return;
      if (!read?.pending || read.scope !== scope || read.serial !== serials.current.catalogue) {
        void reload("catalogue");
        return;
      }
      const result = await read.promise;
      if (!current() || result.serial !== serials.current.catalogue) return;
      if (result.status === "loaded" && !required.confirmed) void reload("catalogue");
    };
    void confirm();
    return () => {
      stopped = true;
    };
  }, [owner, scope, active, foreground, configured, catalogueNeeded, currentPublication, reload]);

  const useForTask = useCallback(
    (item: ResourceItem, callback?: (selection: ResourceSelection) => void) => {
      const current = stateRef.current;
      if (
        !callback ||
        !owner ||
        live.current.owner !== owner ||
        !live.current.active ||
        !live.current.foreground ||
        !live.current.configured ||
        !live.current.catalogueNeeded ||
        current.owner !== owner ||
        current.scope !== scope ||
        live.current.scope !== scope ||
        verifiedAt("catalogue") === undefined ||
        jobs.current.has("catalogue") ||
        (publication.current?.scope === scope && !publication.current.confirmed) ||
        current.catalogue.stale ||
        current.catalogue.loading ||
        current.catalogue.error ||
        !["ready", "active"].includes(item.state)
      )
        return;
      const fresh = current.catalogue.data?.groups
        .flatMap((group) => group.items)
        .find(
          (candidate) =>
            selectionKey(candidate) === selectionKey(item) && candidate.state === item.state,
        );
      const selection = fresh && resourceSelection(fresh);
      if (selection) callback(selection);
    },
    [owner, scope],
  );
  const masked = state.scope === scope && owner ? state : initial(owner, scope);
  const display = <T>(source: Source, value: ResourceLoad<T>): ResourceLoad<T> => ({
    ...value,
    loading: online && value.loading,
    stale: Boolean(value.data && (value.stale || !online || verifiedAt(source) === undefined)),
    error: owner && !online && !value.data ? "unavailable" : value.error,
  });
  return {
    ...masked,
    watchlist: display("watchlist", masked.watchlist),
    follows: {
      ...display("follows", masked.follows),
      loading: Boolean(
        owner &&
        active &&
        foreground &&
        followsNeeded &&
        (masked.follows.loading || (!masked.follows.data && !masked.follows.error)),
      ),
    },
    owner,
    authenticated: Boolean(owner),
    offline: !online,
    canRefresh: Boolean(owner && active && foreground),
    configured,
    publicationBound: Boolean(currentPublication),
    catalogue:
      configured && catalogueNeeded
        ? {
            ...display("catalogue", masked.catalogue),
            stale:
              display("catalogue", masked.catalogue).stale ||
              Boolean(masked.catalogue.data && currentPublication && !currentPublication.confirmed),
          }
        : empty<ResourceCatalogue>(),
    reload,
    saveFollows,
    useForTask,
  };
}
export type ResourceLibraryModel = ReturnType<typeof useResourceLibrary>;
