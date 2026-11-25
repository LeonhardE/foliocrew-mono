"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import { readWatchlistSnapshot, watchlistError, type WatchlistSnapshot } from "@/lib/watchlist";

type WatchlistState = WatchlistSnapshot & {
  sessionKey: string | null;
  loading: boolean;
  loaded: boolean;
  pendingSymbol: string | null;
  error: string;
  message: string;
  messageId: number;
};

const emptyState: WatchlistState = {
  sessionKey: null,
  items: [],
  limit: 50,
  loading: false,
  loaded: false,
  pendingSymbol: null,
  error: "",
  message: "",
  messageId: 0,
};

type WatchlistSync = {
  beforeSave: (revision: number, owner: string) => Promise<void>;
  onSaved: (revision: number, owner: string) => void;
};

export function useWatchlist(enabled = true, sync?: WatchlistSync) {
  const { status, sessionKey, requestPrivate } = useAuth();
  const owner = status === "authenticated" ? sessionKey : null;
  const ownerRef = useRef(owner);
  // Mask private data in the render that observes an account transition, before effects run.
  ownerRef.current = owner;
  const [state, setState] = useState<WatchlistState>(emptyState);
  const requestRef = useRef<{ id: number; controller: AbortController } | null>(null);
  const generationRef = useRef(0);
  const requestedOwner = useRef<string | null>(null);
  const latestSnapshot = useRef<{ owner: string; data: WatchlistSnapshot } | null>(null);
  const currentSync = useRef(sync);
  currentSync.current = sync;

  const loadOrMutate = useCallback(
    async (method: "GET" | "PUT" | "DELETE", symbol?: string) => {
      if (!owner || ownerRef.current !== owner || requestRef.current) return;
      const controller = new AbortController();
      const id = ++generationRef.current;
      requestRef.current = { id, controller };
      const ownsRequest = () => ownerRef.current === owner && generationRef.current === id;
      setState((previous) => ({
        ...(previous.sessionKey === owner ? previous : emptyState),
        sessionKey: owner,
        loading: method === "GET",
        pendingSymbol: method === "GET" ? null : symbol!,
        error: "",
        message: "",
      }));
      const timeout = window.setTimeout(() => {
        controller.abort();
        if (!ownsRequest()) return;
        ++generationRef.current;
        requestRef.current = null;
        setState((previous) => ({
          ...previous,
          loading: false,
          loaded: false,
          pendingSymbol: null,
          error: "The watchlist request took too long. Reload your watchlist to try again.",
        }));
      }, 20_000);
      try {
        const callbacks = currentSync.current;
        const previous =
          latestSnapshot.current?.owner === owner ? latestSnapshot.current.data : null;
        const hadSymbol = previous?.items.some((item) => item.symbol === symbol);
        const expectedChange =
          method !== "GET" && hadSymbol !== undefined && hadSymbol !== (method === "PUT");
        if (
          callbacks &&
          expectedChange &&
          previous?.revision !== undefined &&
          previous.revision !== Number.MAX_SAFE_INTEGER
        ) {
          await callbacks.beforeSave((previous.revision ?? 0) + 1, owner).catch(() => {});
          if (!ownsRequest() || controller.signal.aborted) return;
        }
        const path = `/api/v1/watchlist${method === "GET" ? "" : `/${encodeURIComponent(symbol!)}`}`;
        const response = await requestPrivate(
          "user",
          path + (callbacks ? "?includeRevision=true" : ""),
          owner,
          {
            method,
            signal: controller.signal,
          },
        );
        if (!response.ok) throw new Error(watchlistError(response.status));
        const result = readWatchlistSnapshot(await response.json());
        if (!ownsRequest() || controller.signal.aborted) return;
        latestSnapshot.current = { owner, data: result };
        setState({
          ...result,
          sessionKey: owner,
          loading: false,
          loaded: true,
          pendingSymbol: null,
          error: "",
          message:
            method === "PUT"
              ? `${symbol} added to your watchlist.`
              : method === "DELETE"
                ? `${symbol} removed from your watchlist.`
                : "",
          messageId: method === "GET" ? 0 : id,
        });
        if (
          callbacks &&
          method !== "GET" &&
          typeof result.revision === "number" &&
          result.revision > 0 &&
          result.items.some((item) => item.symbol === symbol) === (method === "PUT") &&
          (previous?.revision !== undefined
            ? result.revision > (previous.revision ?? 0)
            : hadSymbol === undefined || expectedChange)
        )
          callbacks.onSaved(result.revision, owner);
      } catch (error) {
        if (!ownsRequest() || controller.signal.aborted) return;
        setState((previous) => ({
          ...previous,
          loading: false,
          loaded: method === "GET" ? previous.loaded : false,
          pendingSymbol: null,
          error:
            error instanceof Error && error.name !== "TypeError"
              ? error.message
              : watchlistError(503),
        }));
      } finally {
        window.clearTimeout(timeout);
        if (requestRef.current?.id === id) requestRef.current = null;
      }
    },
    [owner, requestPrivate],
  );

  useEffect(() => {
    requestRef.current?.controller.abort();
    requestRef.current = null;
    latestSnapshot.current = null;
    ++generationRef.current;
    setState({ ...emptyState, sessionKey: owner });
    requestedOwner.current = null;
    return () => {
      ++generationRef.current;
      requestRef.current?.controller.abort();
      requestRef.current = null;
    };
  }, [owner, loadOrMutate]);

  useEffect(() => {
    if (!enabled || !owner || requestedOwner.current === owner) return;
    requestedOwner.current = owner;
    void loadOrMutate("GET");
  }, [enabled, owner, loadOrMutate]);

  const visible = owner && state.sessionKey === owner ? state : emptyState;
  useEffect(() => {
    if (!owner || !visible.message) return;
    const messageId = visible.messageId;
    const timeout = window.setTimeout(() => {
      if (ownerRef.current !== owner) return;
      setState((previous) =>
        previous.sessionKey === owner && previous.messageId === messageId
          ? { ...previous, message: "" }
          : previous,
      );
    }, 3_000);
    return () => window.clearTimeout(timeout);
  }, [owner, visible.message, visible.messageId]);

  return {
    ...visible,
    loading: Boolean(owner) && enabled && (visible.loading || (!visible.loaded && !visible.error)),
    authenticated: Boolean(owner),
    busy: visible.loading || visible.pendingSymbol !== null,
    reload: () => loadOrMutate("GET"),
    add: (symbol: string) => loadOrMutate("PUT", symbol),
    remove: (symbol: string) => loadOrMutate("DELETE", symbol),
    dismissMessage: () => {
      if (!owner || ownerRef.current !== owner) return;
      setState((previous) =>
        previous.sessionKey === owner ? { ...previous, message: "" } : previous,
      );
    },
  };
}

export type WatchlistModel = ReturnType<typeof useWatchlist>;
