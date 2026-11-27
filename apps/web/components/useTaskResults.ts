"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { TaskOverviewRead } from "@/lib/task-overview";
import { useAuth } from "./AuthProvider";
import type { HoldingsWorkspace } from "./useHoldingsWorkspace";
import type { TaskCenterModel } from "./useTaskCenter";
import type { TaskModel } from "./useTasks";
import type { PersistentWorkspaceModel } from "./usePersistentWorkspace";
import { DisplayLru, hasFreshWorkspaceDisplay, untilSignal } from "@/lib/workspace-cache";
import { readReportProviders } from "@/lib/report-provider-attribution";
import { readInboxResultLink, clearInboxResultLink } from "@/lib/inbox-link";
import {
  RESULT_CONTRACT as C,
  resultPage,
  resultKey,
  persistentResultMetadata,
  readTaskResult,
  resultRecordPath,
  stateReceipt,
  immutableMetadata,
  type ResultRow,
  type ResultDetail,
} from "@/lib/task-result-reader";
type J = Record<string, any>;
const initialFeed = () => ({ cursor: null as string | null, done: false });
export function useTaskResults(
  workspace: HoldingsWorkspace,
  persistent: PersistentWorkspaceModel | undefined,
  model: TaskModel,
  active: boolean,
  observedResults = "",
  center?: TaskCenterModel,
  overview?: TaskOverviewRead,
  taskResultsVisible = true,
) {
  const auth = useAuth(),
    [visible, setVisible] = useState(
      () => typeof document === "undefined" || document.visibilityState !== "hidden",
    );
  const sessionScope =
    auth.status === "authenticated" &&
    workspace.owner === auth.sessionKey &&
    workspace.phase === "unlocked" &&
    !workspace.needsDeviceApproval
      ? `${auth.sessionKey}:${workspace.vault?.vaultId}:${workspace.vaultGeneration}`
      : null;
  const scope = visible ? sessionScope : null;
  const [state, setState] = useState<{
    scope: string | null;
    rows: ResultRow[];
    loading: boolean;
    ready: boolean;
    complete: boolean;
    error: string;
    detail: ResultDetail | null;
    busy: boolean;
    pending: boolean;
    revision: number;
    selection: string | null;
  }>({
    scope: null,
    rows: [],
    loading: false,
    ready: false,
    complete: false,
    error: "",
    detail: null,
    busy: false,
    pending: false,
    revision: 0,
    selection: null,
  });
  const wanted = useRef(new Map<string, ResultRow>()),
    selections = useRef(new Map<string, string>());
  const [filters, setFilters] = useState<
    Record<string, { actor: string; filter: string; query: string; limit: number }>
  >({});
  const live = useRef({ scope, workspace, auth, model, active, visible, persistent });
  live.current = { scope, workspace, auth, model, active, visible, persistent };
  const uiRevision = useRef(0),
    attributions = useRef(new Map<string, J>());
  const taskPages = useRef(
    new Map<
      string,
      {
        cursor: string | null;
        done: boolean;
        fresh: number;
        busy: boolean;
        observed: string;
        rules: boolean | undefined;
      }
    >(),
  );
  const tabReturn = useRef(false);
  const freshRead = (at: number) =>
    tabReturn.current
      ? hasFreshWorkspaceDisplay(at, Date.now())
      : at > 0 && Date.now() - at >= 0 && Date.now() - at < 30_000;
  const rows = useRef(new Map<string, ResultRow>()),
    feed = useRef(initialFeed()),
    jobs = useRef(new Set<AbortController>()),
    generation = useRef(0),
    loadSerial = useRef(0),
    loading = useRef(false),
    reloadAfter = useRef(false),
    checkedRunResults = useRef(""),
    loadAgain = useRef<(force?: boolean) => Promise<void>>(async () => {}),
    fresh = useRef(0),
    evicted = useRef(false);
  const cache = useRef(
      workspace.displayCache?.reports ?? new DisplayLru<unknown>(10, 16 * 1024 * 1024),
    ),
    titles = useRef(new Map<string, { version: string; title: string }>()),
    failures = useRef(new Set<string>()),
    titleQueue = useRef<ResultRow[]>([]),
    titlePending = useRef(new Set<string>()),
    titleActive = useRef(0);
  const reportProviders = useRef({
    scope: sessionScope,
    providers: {} as Record<string, "muse" | "chatgpt">,
    at: 0,
    ready: false,
    loading: false,
    error: "",
  });
  const selectedSerial = useRef(0),
    pending = useRef<{ scope: string; row: ResultRow; changes: J; packet: J } | null>(null),
    writeBusy = useRef(false),
    attemptedRead = useRef(new Set<string>()),
    scroll = useRef(new Map<string, number>());
  const link = useRef<ReturnType<typeof readInboxResultLink>>(null),
    resolvedLink = useRef<{ scope: string; hash: string; at: number } | null>(null),
    [linkedRow, setLinkedRow] = useState<ResultRow | null>(null),
    [retiredReportLink, setRetiredReportLink] = useState(false),
    channel = useRef<BroadcastChannel | null>(null);
  const update = useCallback((patch: Partial<typeof state>, expected = live.current.scope) => {
    if (expected && live.current.scope === expected)
      setState((s) => ({ ...s, ...patch, scope: expected }));
  }, []);
  const api = useCallback(
    async (path: string, options: any = {}, expected = live.current.scope): Promise<J> => {
      const start = live.current,
        epoch = generation.current;
      if (!expected || start.scope !== expected) throw Error("cancelled");
      const abort = new AbortController();
      jobs.current.add(abort);
      let timedOut = false;
      const timer = setTimeout(() => {
        timedOut = true;
        abort.abort();
      }, 14000);
      const check = () => {
        if (
          abort.signal.aborted ||
          live.current.scope !== expected ||
          generation.current !== epoch ||
          !live.current.visible
        )
          throw Error(timedOut ? "request_timeout" : "cancelled");
      };
      try {
        check();
        const method = options.method ?? "GET",
          send = () =>
            start.auth.requestPrivate("agent-hub", path, start.auth.sessionKey!, {
              ...options,
              signal: abort.signal,
              coalesceDisplay: method === "GET" && !options.fresh,
              headers: { "X-FolioView-Contract": C, ...options.headers },
            });
        let response = await untilSignal(send(), abort.signal, () =>
          Error(timedOut ? "request_timeout" : "cancelled"),
        );
        check();
        if (
          method === "GET" &&
          response.status === 503 &&
          response.headers.get("X-FolioView-Admission-Retry") === "safe" &&
          response.headers.get("Retry-After") === "1"
        ) {
          void response.body?.cancel().catch(() => {});
          await new Promise<void>((resolve, reject) => {
            const cancel = () => {
              clearTimeout(t);
              reject(Error("cancelled"));
            };
            const t = setTimeout(() => {
              abort.signal.removeEventListener("abort", cancel);
              resolve();
            }, 1000);
            abort.signal.addEventListener("abort", cancel, { once: true });
          });
          check();
          response = await untilSignal(send(), abort.signal, () =>
            Error(timedOut ? "request_timeout" : "cancelled"),
          );
          check();
        }
        const stateConflict = method === "PATCH" && response.status === 409;
        if (!response.ok && !stateConflict) {
          void response.body?.cancel().catch(() => {});
          throw Error(
            response.headers.get("X-FolioView-Read-Failure") === "deadline"
              ? "request_timeout"
              : response.status === 404
                ? "not_found"
                : response.status === 409
                  ? "version_conflict"
                  : response.status === 401
                    ? "session_expired"
                    : "request_failed",
          );
        }
        if (!response.body) throw Error("invalid_response");
        const reader = response.body.getReader(),
          chunks: Uint8Array[] = [];
        let size = 0;
        const cancel = () => void reader.cancel().catch(() => {});
        abort.signal.addEventListener("abort", cancel, { once: true });
        try {
          for (;;) {
            const part = await untilSignal(reader.read(), abort.signal, () =>
              Error(timedOut ? "request_timeout" : "cancelled"),
            );
            check();
            if (part.done) break;
            size += part.value.length;
            if (size > 4194304) throw Error("invalid_response");
            chunks.push(part.value);
          }
          const bytes = new Uint8Array(size);
          let offset = 0;
          for (const part of chunks) {
            bytes.set(part, offset);
            offset += part.length;
          }
          const data = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
          check();
          if (!data || typeof data !== "object" || Array.isArray(data))
            throw Error("invalid_response");
          if (stateConflict)
            throw Error(
              data.contractVersion === C && data.error?.code === "version_conflict"
                ? "result_state_version_conflict"
                : "version_conflict",
            );
          return data;
        } finally {
          abort.signal.removeEventListener("abort", cancel);
          cancel();
          try {
            reader.releaseLock();
          } catch {
            /* Cancelled reader may still be pending. */
          }
        }
      } finally {
        clearTimeout(timer);
        jobs.current.delete(abort);
      }
    },
    [],
  );
  const loadReportProviders = useCallback(
    async (force = false) => {
      const start = live.current,
        epoch = generation.current,
        record = reportProviders.current;
      if (
        !start.scope ||
        !start.active ||
        record.scope !== start.scope ||
        record.loading ||
        (!force && record.ready && !record.error && freshRead(record.at))
      )
        return;
      const current = () =>
        live.current.scope === start.scope &&
        live.current.active &&
        generation.current === epoch &&
        reportProviders.current === record;
      record.loading = true;
      record.error = "";
      update({ revision: ++uiRevision.current }, start.scope);
      try {
        if (force) overview?.invalidate(false);
        const snapshot = !force && overview ? await overview.acquireWithFallback() : null;
        if (!current() || !live.current.visible) return;
        const data =
          snapshot?.data.connections ??
          (await api("/api/v2/persistent-connections", {}, start.scope));
        const providers = readReportProviders(data, start.workspace.vault!.vaultId);
        if (!current()) return;
        record.providers = providers;
        record.at = snapshot?.at ?? Date.now();
        record.ready = true;
      } catch (error) {
        if (current())
          record.error =
            error instanceof Error &&
            ["invalid_response", "request_timeout", "request_failed", "session_expired"].includes(
              error.message,
            )
              ? error.message
              : "request_failed";
      } finally {
        if (current()) {
          record.loading = false;
          update({ revision: ++uiRevision.current }, start.scope);
        }
      }
    },
    [api, update, overview],
  );
  const merge = useCallback(
    (incoming: ResultRow[], expected: string) => {
      if (live.current.scope !== expected) return;
      for (const row of incoming) {
        const key = resultKey(row),
          old = rows.current.get(key);
        if (!old || old.metadata.stateVersion <= row.metadata.stateVersion)
          rows.current.set(key, {
            ...row,
            triggerKind:
              attributions.current.get(key)?.triggerKind ?? old?.triggerKind ?? row.triggerKind,
          });
      }
      while (rows.current.size > 2048) {
        const key = rows.current.keys().next().value!;
        rows.current.delete(key);
        titles.current.delete(key);
        failures.current.delete(key);
        wanted.current.delete(key);
        attributions.current.delete(key);
        evicted.current = true;
      }
      update(
        { rows: [...rows.current.values()], ready: true, revision: ++uiRevision.current },
        expected,
      );
    },
    [update],
  );
  const load = useCallback(
    async (force = false, more = false) => {
      const start = live.current;
      if (loading.current) {
        if (force) reloadAfter.current = true;
        return;
      }
      if (!start.scope || !start.active || (!force && !more && freshRead(fresh.current))) return;
      loading.current = true;
      const serial = ++loadSerial.current,
        epoch = generation.current;
      update({ loading: true, error: "" }, start.scope);
      if (force || (!more && fresh.current > 0)) feed.current = initialFeed();
      if (force) {
        rows.current.clear();
        evicted.current = false;
      }
      try {
        if (force || more) overview?.invalidate(false);
        const snapshot = !force && !more && overview ? await overview.acquireWithFallback() : null;
        if (!feed.current.done) {
          if (
            live.current.scope !== start.scope ||
            serial !== loadSerial.current ||
            generation.current !== epoch ||
            !live.current.active
          )
            return;
          const path = `/api/v2/persistent-results/${start.workspace.vault!.vaultId}?limit=20`;
          const cursor = feed.current.cursor;
          const data = snapshot
            ? snapshot.data.feeds.persistent
            : await api(
                path + (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""),
                {},
                start.scope,
              );
          const page = resultPage(data);
          if (live.current.scope !== start.scope || generation.current !== epoch) return;
          feed.current = { cursor: page.nextCursor, done: page.nextCursor === null };
          merge(page.items, start.scope);
        }
        if (live.current.scope === start.scope && generation.current === epoch) {
          fresh.current = snapshot?.at ?? Date.now();
          update(
            {
              complete: feed.current.done && !evicted.current,
              ready: true,
              loading: false,
            },
            start.scope,
          );
        }
      } catch (e) {
        if (live.current.scope === start.scope && generation.current === epoch)
          update(
            { loading: false, error: e instanceof Error ? e.message : "request_failed" },
            start.scope,
          );
      } finally {
        if (serial === loadSerial.current) {
          loading.current = false;
          if (reloadAfter.current && live.current.scope === start.scope && live.current.active) {
            reloadAfter.current = false;
            void loadAgain.current(true);
          }
        }
      }
    },
    [api, merge, update, overview],
  );
  loadAgain.current = load;
  const read = useCallback(
    async (row: ResultRow, freshRead = true) => {
      if (freshRead) overview?.invalidate(false);
      const start = live.current,
        epoch = generation.current;
      if (!start.scope) throw Error("cancelled");
      const assert = () => {
        if (
          live.current.scope !== start.scope ||
          generation.current !== epoch ||
          !live.current.visible
        )
          throw Error("cancelled");
      };
      const result = await readTaskResult({
        row,
        workspace: start.workspace,
        api: (p, o) => api(p, { ...o, fresh: freshRead }, start.scope),
        cache: cache.current,
        scope: start.scope,
        assert,
        fresh: freshRead,
      });
      assert();
      return result;
    },
    [api],
  );
  const pump = useRef<() => void>(() => {});
  pump.current = () => {
    const start = live.current;
    const epoch = generation.current;
    if (!start.scope || !start.active) return;
    while (titleActive.current < 2 && titleQueue.current.length) {
      const row = titleQueue.current.shift()!,
        key = resultKey(row),
        version = JSON.stringify(immutableMetadata(row.metadata));
      if (titlePending.current.has(key)) continue;
      titleActive.current++;
      titlePending.current.add(key);
      void read(row, false)
        .then((detail) => {
          if (
            generation.current === epoch &&
            live.current.scope === start.scope &&
            JSON.stringify(immutableMetadata(rows.current.get(key)?.metadata ?? {})) === version
          )
            titles.current.set(key, { version, title: detail.content.title });
        })
        .catch((error) => {
          if (
            generation.current === epoch &&
            live.current.scope === start.scope &&
            live.current.active &&
            error?.message !== "cancelled"
          )
            failures.current.add(key);
        })
        .finally(() => {
          if (generation.current === epoch && live.current.scope === start.scope) {
            titlePending.current.delete(key);
            titleActive.current--;
            update({ revision: ++uiRevision.current }, start.scope);
            pump.current();
          }
        });
    }
  };
  const open = useCallback(
    async (row: ResultRow) => {
      const start = live.current;
      if (!start.scope || !start.active) return;
      const serial = ++selectedSerial.current;
      attemptedRead.current.delete(`${start.scope}:${resultKey(row)}:${row.metadata.stateVersion}`);
      update({ busy: true, error: "", detail: null }, start.scope);
      try {
        // Ordinary task read applies current deletion visibility before a cached report can be shown.
        await api(`/api/v2/tasks/${row.metadata.taskId}`, { fresh: true }, start.scope);
        const detail = await read(row, true);
        if (serial !== selectedSerial.current || live.current.scope !== start.scope) return;
        merge([detail.row], start.scope);
        titles.current.set(resultKey(row), {
          version: JSON.stringify(immutableMetadata(detail.row.metadata)),
          title: detail.content.title,
        });
        selections.current.set(row.metadata.taskId, resultKey(row));
        update({ detail, busy: false, selection: resultKey(row) }, start.scope);
      } catch (e) {
        if (serial === selectedSerial.current)
          update(
            { busy: false, error: e instanceof Error ? e.message : "request_failed" },
            start.scope,
          );
      }
    },
    [api, read, merge, update],
  );
  const publishState = useCallback(
    (row: ResultRow, expected: string) => {
      merge([row], expected);
      if (live.current.scope === expected)
        setState((s) => ({
          ...s,
          detail:
            s.detail &&
            resultKey(s.detail.row) === resultKey(row) &&
            s.detail.row.metadata.stateVersion <= row.metadata.stateVersion &&
            JSON.stringify(immutableMetadata(s.detail.row.metadata)) ===
              JSON.stringify(immutableMetadata(row.metadata))
              ? { ...s.detail, row }
              : s.detail,
        }));
    },
    [merge],
  );
  const change = useCallback(
    async (row: ResultRow, changes: J, mode: "edit" | "retry" | "presented" = "edit") => {
      const start = live.current;
      if (!start.scope || !start.workspace.canWriteState || writeBusy.current) return;
      const scope = start.scope;
      const selection = selectedSerial.current;
      const assertCurrent = () => {
        if (
          live.current.scope !== scope ||
          !live.current.workspace.canWriteState ||
          (mode === "presented" &&
            (!live.current.visible || !live.current.active || selection !== selectedSerial.current))
        )
          throw Error("cancelled");
      };
      writeBusy.current = true;
      update({ busy: true, error: "" }, scope);
      try {
        if (pending.current && mode !== "retry") throw Error("state_pending");
        const path = resultRecordPath(start.workspace.vault!.vaultId, row.metadata.resultId);
        const readMetadata = async () => {
          const raw = await api(path, { fresh: true }, scope);
          const meta = persistentResultMetadata(raw.metadata);
          if (
            JSON.stringify(immutableMetadata(meta)) !==
            JSON.stringify(immutableMetadata(row.metadata))
          )
            throw Error("version_conflict");
          return meta;
        };
        const prepare = async (meta: J) => {
          assertCurrent();
          const current = { ...row, metadata: meta };
          publishState(current, scope);
          if (Object.keys(changes).every((k) => meta[k] === changes[k])) return false;
          const packet = await start.workspace.signPersistentResultState({
            metadata: meta,
            changes,
          });
          assertCurrent();
          pending.current = { scope, row: current, changes, packet };
          update({ pending: true }, scope);
          return true;
        };
        const submit = async () => {
          const p = pending.current;
          if (!p || p.scope !== scope) throw Error("cancelled");
          const ack = await api(
            path + "/state",
            {
              method: "PATCH",
              json: { contractVersion: C, command: p.packet.command },
              headers: {
                "Idempotency-Key": p.packet.operationId,
                "X-FolioView-Author-Key": p.packet.authorKeyId,
              },
            },
            scope,
          );
          return stateReceipt(p.row, p.changes, ack);
        };
        if (
          mode !== "retry" &&
          !(await prepare(mode === "presented" ? row.metadata : await readMetadata()))
        )
          return;
        let saved: ResultRow;
        try {
          saved = await submit();
        } catch (error) {
          // Rebase just the read acknowledgement after a definite version rejection.
          // A lost response must retain its original signed packet for exact replay.
          if (
            mode !== "presented" ||
            !(error instanceof Error) ||
            error.message !== "result_state_version_conflict"
          )
            throw error;
          const meta = await readMetadata();
          assertCurrent();
          if (meta.stateVersion <= row.metadata.stateVersion) throw error;
          pending.current = null;
          update({ pending: false }, scope);
          if (!(await prepare(meta))) return;
          saved = await submit();
        }
        pending.current = null;
        publishState(saved, scope);
        update({ pending: false }, scope);
      } catch (e) {
        update(
          {
            error: pending.current
              ? "state_pending"
              : e instanceof Error
                ? e.message
                : "request_failed",
            pending: Boolean(pending.current),
          },
          start.scope,
        );
      } finally {
        writeBusy.current = false;
        update({ busy: false }, start.scope);
      }
    },
    [api, publishState, update],
  );
  const displayedSelection = selectedSerial.current;
  const presented = useCallback(
    (detail: ResultDetail) => {
      const key = `${live.current.scope}:${resultKey(detail.row)}:${detail.row.metadata.stateVersion}`;
      if (
        !live.current.scope ||
        live.current.scope !== state.scope ||
        !live.current.visible ||
        !live.current.active ||
        displayedSelection !== selectedSerial.current ||
        detail.row.metadata !== state.detail?.row.metadata ||
        !live.current.workspace.canWriteState ||
        detail.row.metadata.read ||
        attemptedRead.current.has(key) ||
        pending.current
      )
        return;
      attemptedRead.current.add(key);
      void change(detail.row, { read: true }, "presented");
    },
    [change, displayedSelection, state.scope, state.detail],
  );
  const task = model.selected?.taskId ?? "",
    f = (scope && active && state.scope === scope ? filters[task] : null) ?? {
      actor: "all",
      filter: "all",
      query: "",
      limit: 20,
    };
  const current =
    scope && active && state.scope === scope
      ? state
      : {
          ...state,
          rows: [],
          detail: null,
          selection: null,
          ready: false,
          loading: Boolean(scope),
          error: "",
          pending: false,
          busy: false,
        };
  const sourceProviders =
    reportProviders.current.scope === scope
      ? reportProviders.current
      : {
          providers: {} as Record<string, "muse" | "chatgpt">,
          ready: false,
          loading: false,
          error: "",
        };
  const providerFor = (row: ResultRow) => {
    if (!scope || live.current.scope !== scope || !live.current.active || !live.current.visible)
      return "agent";
    const declared = attributions.current.get(resultKey(row))?.provider;
    if (declared !== undefined) return ["muse", "chatgpt"].includes(declared) ? declared : "agent";
    return Object.hasOwn(sourceProviders.providers, row.metadata.connectionId)
      ? sourceProviders.providers[row.metadata.connectionId]
      : "agent";
  };
  const taskRows = current.rows
    .filter((r) => r.metadata.taskId === task)
    .sort(
      (a, b) =>
        new Date(
          typeof b.metadata.receivedAt === "number"
            ? b.metadata.receivedAt * 1000
            : b.metadata.receivedAt,
        ).getTime() -
        new Date(
          typeof a.metadata.receivedAt === "number"
            ? a.metadata.receivedAt * 1000
            : a.metadata.receivedAt,
        ).getTime(),
    );
  const filtered = taskRows
    .filter(
      (r) =>
        (f.actor === "all" || providerFor(r) === f.actor) &&
        (f.filter === "archived"
          ? r.metadata.archived
          : !r.metadata.archived &&
            (f.filter === "all" ||
              (f.filter === "unread" && !r.metadata.read) ||
              (f.filter === "starred" && r.metadata.starred))),
    )
    .filter(
      (r) =>
        !f.query ||
        titles.current
          .get(resultKey(r))
          ?.title.toLocaleLowerCase()
          .includes(f.query.toLocaleLowerCase()),
    );
  const visibleRows = filtered.slice(0, f.limit),
    signature = visibleRows
      .map((r) => resultKey(r) + JSON.stringify(immutableMetadata(r.metadata)))
      .join("|");
  useEffect(() => {
    titleQueue.current = [
      ...new Map(
        [...wanted.current.values()]
          .filter((r) => r.metadata.taskId === task)
          .map((r) => [resultKey(r), r]),
      ).values(),
    ].filter(
      (r) =>
        titles.current.get(resultKey(r))?.version !==
          JSON.stringify(immutableMetadata(r.metadata)) &&
        !failures.current.has(resultKey(r)) &&
        !titlePending.current.has(resultKey(r)),
    );
    pump.current();
  }, [scope, active, signature, state.revision]);
  useEffect(() => {
    const changed = () => {
      const v = document.visibilityState !== "hidden";
      live.current.visible = v;
      tabReturn.current = v && live.current.active;
      setVisible(v);
      if (!v) {
        for (const j of jobs.current) j.abort();
        setState((previous) => ({ ...previous, loading: false, busy: false }));
      }
    };
    document.addEventListener("visibilitychange", changed);
    return () => document.removeEventListener("visibilitychange", changed);
  }, []);
  useEffect(() => {
    generation.current++;
    loadSerial.current++;
    selectedSerial.current++;
    for (const j of jobs.current) j.abort();
    rows.current.clear();
    reportProviders.current = {
      scope: sessionScope,
      providers: {},
      at: 0,
      ready: false,
      loading: false,
      error: "",
    };
    feed.current = initialFeed();
    titles.current.clear();
    wanted.current.clear();
    failures.current.clear();
    titleQueue.current = [];
    titlePending.current.clear();
    titleActive.current = 0;
    cache.current.clear();
    attributions.current.clear();
    taskPages.current.clear();
    resolvedLink.current = null;
    checkedRunResults.current = "";
    reloadAfter.current = false;
    pending.current = null;
    attemptedRead.current.clear();
    fresh.current = 0;
    tabReturn.current = false;
    loading.current = false;
    evicted.current = false;
    scroll.current.clear();
    selections.current.clear();
    setFilters({});
    setState({
      scope: sessionScope,
      rows: [],
      loading: false,
      ready: false,
      complete: false,
      error: "",
      detail: null,
      busy: false,
      pending: false,
      revision: 0,
      selection: null,
    });
  }, [sessionScope]);
  useEffect(() => {
    if (!active) tabReturn.current = false;
    if (scope && active) {
      void load();
      void loadReportProviders();
    }
  }, [scope, active, load, loadReportProviders]);
  useEffect(() => {
    if (!scope || !active) return;
    return () => {
      generation.current++;
      selectedSerial.current++;
      loadSerial.current++;
      if (loading.current) fresh.current = 0;
      if (reportProviders.current.scope === scope) reportProviders.current.loading = false;
      loading.current = false;
      reloadAfter.current = false;
      titleQueue.current = [];
      titlePending.current.clear();
      titleActive.current = 0;
      for (const job of jobs.current) job.abort();
      update({ loading: false, busy: false }, scope);
    };
  }, [scope, active, update]);
  // Read one selected-task page, including sparse history, only on entry or explicit More.
  const loadTaskPage = useCallback(
    async (target: string, rules: boolean | undefined, force = false, more = false) => {
      const start = live.current,
        epoch = generation.current;
      if (!start.scope || !start.active || !target) return;
      const previous = taskPages.current.get(target);
      if (
        (previous?.busy && previous.observed === observedResults && previous.rules === rules) ||
        (!force &&
          !more &&
          previous &&
          freshRead(previous.fresh) &&
          previous.observed === observedResults &&
          previous.rules === rules) ||
        (!force && more && previous?.done)
      )
        return;
      const pageState =
        force || !previous || !more
          ? { cursor: null, done: false, fresh: 0, busy: false, observed: observedResults, rules }
          : previous;
      taskPages.current.delete(target);
      taskPages.current.set(target, pageState);
      while (taskPages.current.size > 32)
        taskPages.current.delete(taskPages.current.keys().next().value!);
      pageState.busy = true;
      update({ revision: ++uiRevision.current }, start.scope);
      const current = () =>
        live.current.scope === start.scope &&
        generation.current === epoch &&
        live.current.active &&
        live.current.model.selected?.taskId === target &&
        taskPages.current.get(target) === pageState;
      try {
        const base = `/api/v3/task-center/${start.workspace.vault!.vaultId}/tasks/${target}`;
        // Callers without a shared verified center model retain the legacy read adapter.
        const enrolled = rules ?? Boolean((await api(base, {}, start.scope)).rules);
        if (!current()) return;
        if (!enrolled) {
          pageState.done = true;
          pageState.fresh = Date.now();
          return;
        }
        const page = await api(
          base + "/results/query",
          {
            method: "POST",
            json: { contractVersion: C, request: { limit: 50, cursor: pageState.cursor } },
          },
          start.scope,
        );
        if (!current()) return;
        if (
          page.contractVersion !== C ||
          page.profile !== "folioview.task-center.v1" ||
          !Array.isArray(page.items) ||
          page.items.length > 50 ||
          !(
            page.nextCursor === null ||
            (typeof page.nextCursor === "string" &&
              page.nextCursor.length > 0 &&
              page.nextCursor.length <= 4096 &&
              page.nextCursor !== pageState.cursor)
          )
        )
          throw Error("invalid_response");
        const parsed: ResultRow[] = [];
        for (const item of page.items) {
          if (item.kind === "foreground") continue;
          if (
            item.kind !== "persistent" ||
            !["manual", "scheduled", "legacy_unknown"].includes(item.triggerKind)
          )
            throw Error("invalid_response");
          const metadata = persistentResultMetadata(item.metadata);
          if (metadata.taskId !== target) throw Error("invalid_response");
          const row: ResultRow = { kind: "persistent", metadata, triggerKind: item.triggerKind };
          parsed.push(row);
        }
        if (new Set(parsed.map(resultKey)).size !== parsed.length) throw Error("invalid_response");
        for (const item of page.items) {
          if (item.kind !== "persistent") continue;
          attributions.current.set(`persistent:${item.metadata.resultId}`, {
            triggerKind: item.triggerKind,
            provider: item.attribution?.provider,
            taskId: target,
          });
        }
        pageState.cursor = page.nextCursor;
        pageState.done = page.nextCursor === null;
        pageState.fresh = Date.now();
        merge(parsed, start.scope);
      } catch (e) {
        if (current())
          update({ error: e instanceof Error ? e.message : "request_failed" }, start.scope);
      } finally {
        pageState.busy = false;
        if (current()) update({ revision: ++uiRevision.current }, start.scope);
      }
    },
    [api, merge, update, observedResults],
  );
  const record = center?.selectedRecord;
  const selectedRecord = record?.taskId === task ? record : undefined;
  const selectedRules = center ? Boolean(selectedRecord?.rules) : undefined;
  const readSelectedPage = (force: boolean, more = false) =>
    !center || selectedRecord ? loadTaskPage(task, selectedRules, force, more) : undefined;
  useEffect(() => {
    if (scope && active && taskResultsVisible && task && (!center || selectedRecord))
      void loadTaskPage(task, selectedRules);
  }, [scope, active, taskResultsVisible, task, selectedRecord, selectedRules, loadTaskPage]);
  useEffect(() => {
    if (
      !scope ||
      !active ||
      state.scope !== scope ||
      state.loading ||
      loading.current ||
      checkedRunResults.current === observedResults
    )
      return;
    // Let the current feed finish merging before treating a run receipt as a new report.
    const previous = new Set(checkedRunResults.current.split("|"));
    checkedRunResults.current = observedResults;
    const missing = observedResults
      .split("|")
      .some(
        (id) =>
          id.startsWith("presult_") && !previous.has(id) && !rows.current.has(`persistent:${id}`),
      );
    if (missing) void load(true);
  }, [scope, active, observedResults, state.scope, state.loading, state.revision, load]);
  useEffect(() => {
    selectedSerial.current++;
    update({
      detail: null,
      selection: selections.current.get(task) ?? null,
    });
  }, [task, update]);
  useEffect(() => {
    if (!active) return;
    let stopped = false;
    const resolve = async (revisit: boolean) => {
      const hash = window.location.hash;
      const value = readInboxResultLink(hash);
      link.current = value;
      const retired = value !== null && !value.resultId.startsWith("presult_");
      setRetiredReportLink(retired);
      if (!scope) return;
      const saved = resolvedLink.current;
      if (
        revisit &&
        tabReturn.current &&
        saved?.scope === scope &&
        saved.hash === hash &&
        hasFreshWorkspaceDisplay(saved.at, Date.now())
      )
        return;
      resolvedLink.current = null;
      setLinkedRow(null);
      if (!value || retired) return;
      try {
        if (value.revision !== undefined && value.revision !== 1) throw Error("not_found");
        const raw = await api(resultRecordPath(workspace.vault!.vaultId, value.resultId));
        const meta = persistentResultMetadata(raw.metadata);
        await api(`/api/v2/tasks/${meta.taskId}`, { fresh: true });
        if (!stopped && link.current === value) {
          resolvedLink.current = { scope, hash, at: Date.now() };
          setLinkedRow({ kind: "persistent", metadata: meta, triggerKind: "legacy_unknown" });
        }
      } catch {
        if (!stopped && link.current === value) update({ error: "not_found" });
      }
    };
    void resolve(true);
    const navigate = () => void resolve(false);
    window.addEventListener("hashchange", navigate);
    window.addEventListener("popstate", navigate);
    return () => {
      stopped = true;
      window.removeEventListener("hashchange", navigate);
      window.removeEventListener("popstate", navigate);
    };
  }, [scope, active, api, update, workspace.vault?.vaultId]);
  useEffect(() => {
    if (!scope || !active || !linkedRow || model.busy || model.dirty || model.pending) return;
    if (model.selected?.taskId !== linkedRow.metadata.taskId) {
      void model.openTask(linkedRow.metadata.taskId);
      return;
    }
    const r = linkedRow;
    setLinkedRow(null);
    void open(r);
  }, [
    scope,
    active,
    linkedRow,
    model.busy,
    model.dirty,
    model.pending,
    model.selected?.taskId,
    model.openTask,
    open,
  ]);
  useEffect(() => {
    if (!scope) return;
    const invalidate = (detail: J, broadcast: boolean) => {
      const v = live.current.workspace.vault;
      if (!v || detail.vaultId !== v.vaultId || detail.rootKeyId !== v.rootKeyId) return;
      generation.current++;
      selectedSerial.current++;
      loadSerial.current++;
      loading.current = false;
      fresh.current = 0;
      resolvedLink.current = null;
      taskPages.current.delete(detail.taskId);
      cache.current.clear();
      titles.current.clear();
      wanted.current.clear();
      titleQueue.current = [];
      failures.current.clear();
      for (const j of jobs.current) j.abort();
      live.current.model.invalidateTask?.(detail.taskId, detail.action === "restore");
      live.current.persistent?.invalidateTask?.(detail.taskId);
      if (detail.action === "trash") {
        selections.current.delete(detail.taskId);
        for (const [key, row] of rows.current)
          if (row.metadata.taskId === detail.taskId) rows.current.delete(key);
        if (pending.current?.row.metadata.taskId === detail.taskId) pending.current = null;
      }
      update({
        rows: [...rows.current.values()],
        detail: null,
        pending: Boolean(pending.current),
        revision: ++uiRevision.current,
      });
      if (broadcast) channel.current?.postMessage(detail);
      void load(true);
      void live.current.model.reloadTasks();
    };
    const event = (e: Event) => invalidate((e as CustomEvent).detail ?? {}, true);
    window.addEventListener("folioview-task-lifecycle", event);
    if (typeof BroadcastChannel !== "undefined") {
      const c = new BroadcastChannel("folioview-task-lifecycle");
      channel.current = c;
      c.onmessage = (e) => invalidate(e.data ?? {}, false);
    }
    return () => {
      window.removeEventListener("folioview-task-lifecycle", event);
      channel.current?.close();
      channel.current = null;
    };
  }, [scope, load, update]);
  const unreadCounts: Record<string, number> = {};
  for (const row of current.rows)
    if (!row.metadata.read && !row.metadata.archived)
      unreadCounts[row.metadata.taskId] = (unreadCounts[row.metadata.taskId] ?? 0) + 1;
  return {
    scope,
    canWrite: Boolean(scope && workspace.canWriteState),
    wantTitle: (row: ResultRow) => {
      if (!scope || !active) return;
      const key = resultKey(row);
      wanted.current.set(key, row);
      if (
        !titlePending.current.has(key) &&
        !failures.current.has(key) &&
        titles.current.get(key)?.version !== JSON.stringify(immutableMetadata(row.metadata))
      ) {
        titleQueue.current.push(row);
        pump.current();
      }
    },
    stopTitle: (row: ResultRow) => wanted.current.delete(resultKey(row)),
    rows: visibleRows,
    allTaskRows: taskRows,
    loading:
      current.loading || sourceProviders.loading || Boolean(taskPages.current.get(task)?.busy),
    ready: current.ready && sourceProviders.ready,
    complete:
      current.complete &&
      sourceProviders.ready &&
      !sourceProviders.loading &&
      !sourceProviders.error &&
      (!task || taskPages.current.get(task)?.done === true),
    error: current.error || sourceProviders.error,
    retiredReportLink: active && retiredReportLink,
    busy: current.busy,
    detail: current.detail
      ? {
          ...current.detail,
          row: {
            ...current.detail.row,
            triggerKind:
              attributions.current.get(resultKey(current.detail.row))?.triggerKind ??
              current.detail.row.triggerKind,
          },
        }
      : null,
    selection: current.selection,
    pending: current.pending,
    unreadCounts,
    partial:
      !current.complete ||
      Boolean(taskResultsVisible && task && taskPages.current.get(task)?.done !== true),
    filters: f,
    actors: [...new Set(taskRows.map(providerFor))],
    providerFor,
    title: (r: ResultRow) =>
      scope && active && state.scope === scope
        ? titles.current.get(resultKey(r))?.version ===
          JSON.stringify(immutableMetadata(r.metadata))
          ? titles.current.get(resultKey(r))!.title
          : null
        : null,
    titleFailed: (r: ResultRow) => failures.current.has(resultKey(r)),
    retryTitle: (r: ResultRow) => {
      failures.current.delete(resultKey(r));
      update({ revision: ++uiRevision.current });
    },
    setFilter: (patch: Partial<typeof f>) =>
      setFilters((s) => ({ ...s, [task]: { ...f, ...patch, limit: 20 } })),
    windowed: evicted.current,
    hasMore:
      filtered.length > f.limit ||
      !feed.current.done ||
      Boolean(task && taskPages.current.get(task)?.done !== true),
    more: async () => {
      setFilters((s) => ({ ...s, [task]: { ...f, limit: f.limit + 20 } }));
      if (filtered.length <= f.limit)
        await Promise.all([load(false, true), readSelectedPage(false, true)]);
    },
    reload: () => Promise.all([load(true), readSelectedPage(true), loadReportProviders(true)]),
    open,
    close: () => {
      selectedSerial.current++;
      update({ detail: null });
      link.current = null;
      setLinkedRow(null);
      setRetiredReportLink(false);
      clearInboxResultLink();
    },
    presented,
    change: (row: ResultRow, changes: J) => change(row, changes),
    retryState: () => {
      const p = pending.current;
      if (p) void change(p.row, p.changes, "retry");
    },
    discardState: () => {
      if (!writeBusy.current) {
        pending.current = null;
        update({ pending: false, error: "" });
        void load(true);
      }
    },
    linkedBlocked: Boolean(linkedRow && model.dirty),
    scroll,
  };
}
export type TaskResultsModel = ReturnType<typeof useTaskResults>;
