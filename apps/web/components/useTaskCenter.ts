"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { SelectedTaskDetail } from "./useTasks";
import type { TaskDetailRead } from "@/lib/task-detail-read";
import type { TaskOverviewRead } from "@/lib/task-overview";
import { useAuth } from "./AuthProvider";
import type { HoldingsWorkspace } from "./useHoldingsWorkspace";
import { boundedJson, untilSignal } from "@/lib/workspace-cache";
import type { TaskMetadata, Vault } from "@/lib/encrypted-types";
import { readReportProviders } from "@/lib/report-provider-attribution";
const CONTRACT = "folioview.agent-workspace.v2.0";
type J = Record<string, any>;
type ExecutorDisplay = { status: "ready" | "loading" | "error"; providers: string[] };
const ready = (providers: string[] = []): ExecutorDisplay => ({ status: "ready", providers });
const taskHead = (meta: TaskMetadata | null) =>
  meta && [
    meta.taskId,
    meta.taskVersion,
    meta.executionEpoch,
    meta.envelopeFingerprint,
    meta.status,
  ];

// The legacy GET is Owner-authenticated display metadata. Its label cannot supply a grant.
async function legacyConnection(value: J, meta: TaskMetadata, vault: Vault, uid?: string) {
  if (value.contractVersion !== CONTRACT || value.profile !== "folioview.persistent-content.v1")
    throw Error("invalid_response");
  if (value.authority === null && value.envelope === null) return null;
  const c = value.authority?.context;
  const subject =
    vault.archive?.ownerSubject ??
    (uid &&
      Array.from(
        new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(uid))),
        (b) => b.toString(16).padStart(2, "0"),
      ).join(""));
  if (
    !subject ||
    !c ||
    !value.envelope ||
    c.ownerSubject !== subject ||
    c.vaultId !== vault.vaultId ||
    c.rootKeyId !== vault.rootKeyId ||
    c.objectType !== "task" ||
    c.taskId !== meta.taskId ||
    c.objectId !== meta.taskId ||
    !Number.isSafeInteger(c.taskVersion) ||
    c.taskVersion < 1 ||
    !Number.isSafeInteger(c.executionEpoch) ||
    c.executionEpoch < 1 ||
    c.taskVersion > meta.taskVersion ||
    c.executionEpoch > meta.executionEpoch ||
    typeof c.connectionId !== "string" ||
    !/^[A-Za-z0-9_-]{1,128}$/.test(c.connectionId)
  )
    throw Error("invalid_response");
  if (c.taskVersion < meta.taskVersion || c.executionEpoch < meta.executionEpoch) return null;
  if (c.ownerTaskFingerprint !== meta.envelopeFingerprint) throw Error("version_conflict");
  return c.connectionId as string;
}
export function useTaskCenter(
  workspace: HoldingsWorkspace,
  active: boolean,
  selected: TaskMetadata | null,
  overview?: TaskOverviewRead,
  selectedDetail?: SelectedTaskDetail,
) {
  const auth = useAuth(),
    owner = auth.status === "authenticated" ? auth.sessionKey : null;
  const scope =
    owner &&
    workspace.owner === owner &&
    workspace.phase === "unlocked" &&
    !workspace.needsDeviceApproval
      ? `${owner}:${workspace.vault?.vaultId}:${workspace.vaultGeneration}`
      : null;
  const [state, setState] = useState<{
    scope: string | null;
    enabled: boolean;
    capabilityState: "loading" | "ready" | "error";
    loading: boolean;
    busy: boolean;
    error: string;
    detailFailure: string | null;
    detailLoading: string | null;
    records: Record<string, J>;
    manual: Record<string, J[]>;
    pending: J | null;
    trash: J[];
    trashCursor: string | null;
  }>({
    scope: null,
    enabled: false,
    capabilityState: "loading",
    loading: false,
    busy: false,
    error: "",
    detailFailure: null,
    detailLoading: null,
    records: {},
    manual: {},
    pending: null,
    trash: [],
    trashCursor: null,
  });
  const selectedKey = JSON.stringify([
    scope,
    workspace.vault?.rootKeyId,
    workspace.vault?.version,
    taskHead(selected),
  ]);
  const live = useRef({ scope, workspace, owner, active, selected, selectedKey, selectedDetail });
  live.current = { scope, workspace, owner, active, selected, selectedKey, selectedDetail };
  const selectedHistories = useRef(new WeakMap<SelectedTaskDetail, Promise<J>>());
  const combinedEvidence = useRef(
    new WeakMap<J, Pick<TaskDetailRead, "legacy" | "attribution"> & { selection: symbol }>(),
  );
  const runVisit = useRef({ key: selectedKey, active });
  if (runVisit.current.key !== selectedKey || runVisit.current.active !== active)
    runVisit.current = { key: selectedKey, active };
  const visit = runVisit.current;
  const recordHeads = useRef(new Map<string, { key: string; at: number }>());
  const runReceipts = useRef(new WeakMap<J, number>());
  const [runRead, setRunRead] = useState<{
    visit: typeof visit;
    record: J | undefined;
    status: "ready" | "error";
  } | null>(null);
  const [runAttempt, setRunAttempt] = useState(0);
  const runGate = useRef({ key: "", ready: false, running: false });
  const legacyCache = useRef(new WeakMap<J, string[]>());
  const [legacy, setLegacy] = useState<{
    key: string;
    record: J;
    value: ExecutorDisplay;
    refreshRecord?: boolean;
  } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const reads = useRef(
      new Map<string, { key: string; source?: SelectedTaskDetail; promise: Promise<J> }>(),
    ),
    generations = useRef(new Map<string, symbol>()),
    writes = useRef(false),
    controllers = useRef(new Set<AbortController>());
  const api = useCallback(
    async (
      path: string,
      options: {
        method?: "POST";
        json?: unknown;
        operation?: string;
        signal?: AbortSignal;
        display?: boolean;
      } = {},
    ): Promise<J> => {
      const start = live.current;
      if (options.method) overview?.invalidate();
      if (!start.owner) throw Error("session_expired");
      const control = new AbortController();
      controllers.current.add(control);
      const abort = () => control.abort();
      if (options.signal?.aborted) abort();
      else options.signal?.addEventListener("abort", abort, { once: true });
      let timedOut = false;
      const cancelled = () => Error(timedOut ? "request_timeout" : "cancelled");
      const timer = setTimeout(() => {
        timedOut = true;
        control.abort();
      }, 14000);
      try {
        const response = await untilSignal(
          auth.requestPrivate("agent-hub", path, start.owner, {
            method: options.method ?? "GET",
            json: options.json,
            ...(options.display ? { coalesceDisplay: true } : {}),
            signal: control.signal,
            headers: {
              "X-FolioView-Contract": CONTRACT,
              ...(options.operation ? { "Idempotency-Key": options.operation } : {}),
            },
          }),
          control.signal,
          cancelled,
        );
        if (live.current.owner !== start.owner || live.current.scope !== start.scope)
          throw Error("cancelled");
        if (!response.ok) {
          void response.body?.cancel().catch(() => {});
          throw Error(
            response.status === 404
              ? "not_found"
              : response.status === 409
                ? "version_conflict"
                : response.status === 403
                  ? "authorization_changed"
                  : response.status >= 500
                    ? "service_unavailable"
                    : "request_failed",
          );
        }
        const data = await boundedJson(response, 1048576, control.signal, cancelled);
        if (!data || typeof data !== "object" || Array.isArray(data))
          throw Error("invalid_response");
        if (live.current.scope !== start.scope || live.current.owner !== start.owner)
          throw Error("cancelled");
        return data;
      } finally {
        clearTimeout(timer);
        controllers.current.delete(control);
        options.signal?.removeEventListener("abort", abort);
      }
    },
    [auth.requestPrivate, overview],
  );
  const error = (e: unknown) => (e instanceof Error ? e.message : "request_failed");
  const update = useCallback((value: Partial<typeof state>, expected = live.current.scope) => {
    if (expected && live.current.scope === expected)
      setState((s) => ({ ...s, ...value, scope: expected }));
  }, []);
  const base = useCallback(
    (task: string) => `/api/v3/task-center/${live.current.workspace.vault!.vaultId}/tasks/${task}`,
    [],
  );
  // Invalidate the visible receipt even when an assignment changes without a new task version.
  const invalidateDetail = useCallback((task: string) => {
    generations.current.set(task, Symbol());
    reads.current.delete(task);
    recordHeads.current.delete(task);
  }, []);
  const load = useCallback(
    async (task: string, force = false) => {
      const start = live.current;
      if (!start.scope || !start.active || start.selected?.taskId !== task) return null;
      const meta = start.selected,
        key = start.selectedKey;
      const receipt = recordHeads.current.get(task);
      const age = receipt ? Date.now() - receipt.at : Infinity;
      if (!force && receipt?.key === key && age >= 0 && age < 15000) return null;
      const source =
        !force &&
        start.selectedDetail?.current() &&
        start.selectedDetail.scope === start.scope &&
        start.selectedDetail.vaultVersion === start.workspace.vault?.version &&
        JSON.stringify(taskHead(start.selectedDetail.metadata)) === JSON.stringify(taskHead(meta))
          ? start.selectedDetail
          : undefined;
      const inFlight = reads.current.get(task);
      if (inFlight?.key === key && inFlight.source === source) return inFlight.promise;
      const generation = Symbol();
      generations.current.set(task, generation);
      const sameGeneration = () =>
        live.current.scope === start.scope &&
        live.current.active &&
        generations.current.get(task) === generation;
      const promise = (async () => {
        update({ detailLoading: key, detailFailure: null }, start.scope);
        try {
          const selectionRead = source?.read();
          if (source && !selectedHistories.current.has(source)) {
            // Read run history beside the combined task/vault receipt. Its result is
            // consumed only for this visit’s verified task.
            const history = api(base(task) + "/manual", { signal: source.signal });
            // Selection can end before the history consumer mounts.
            void history.catch(() => {});
            selectedHistories.current.set(source, history);
          }
          const combined = selectionRead ? await selectionRead : undefined;
          const data = combined ? combined.state : await api(base(task));
          const checked = await start.workspace.verifyTaskCenterState(data);
          if (!sameGeneration() || (source && !source.current())) return {};
          if (
            checked.taskId !== task ||
            checked.taskVersion !== meta.taskVersion ||
            checked.executionEpoch !== meta.executionEpoch
          )
            throw Error("version_conflict");
          if (combined && source)
            combinedEvidence.current.set(checked, {
              selection: source.id,
              legacy: combined.legacy,
              attribution: combined.attribution,
            });
          recordHeads.current.set(task, { key, at: Date.now() });
          const visible = live.current.selectedKey === key;
          setState((s) => ({
            ...s,
            scope: start.scope,
            records: { ...s.records, [task]: checked },
            ...(visible ? { detailLoading: null, detailFailure: null } : {}),
          }));
          return data;
        } catch (e) {
          if (sameGeneration() && live.current.selectedKey === key && error(e) !== "cancelled")
            update({ detailFailure: key, detailLoading: null }, start.scope);
          return {};
        } finally {
          if (generations.current.get(task) === generation) reads.current.delete(task);
        }
      })();
      reads.current.set(task, { key, source, promise });
      return promise;
    },
    [api, base, update],
  );
  const send = useCallback(
    async (packet: J) => {
      const start = live.current;
      const path =
        base(packet.taskId) + (packet.action === "manual_intent" ? "/manual" : "/commands");
      const receipt = await api(path, {
        method: "POST",
        json: packet.body,
        operation: packet.operationId,
      });
      await start.workspace.finishTaskCenterPending(packet.taskId, receipt);
      if (live.current.scope !== start.scope) throw Error("cancelled");
      invalidateDetail(packet.taskId);
      if (packet.action === "manual_intent" && live.current.scope === start.scope) {
        const encoded = packet.body.command.payload.replaceAll("-", "+").replaceAll("_", "/");
        const p = JSON.parse(
          new TextDecoder().decode(Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0))),
        );
        const pending = {
          receipt,
          snapshot: {
            requestId: packet.operationId,
            taskId: packet.taskId,
            requestedAt: receipt.acceptedAt,
            executors: p.intent.assignments.map((a: J) => ({
              ...a,
              runId: null,
              resultId: null,
              stage: "waiting",
            })),
          },
          aggregate: {
            state: "waiting",
            hasActiveExecutors: true,
            counts: { waiting: p.intent.assignments.length },
          },
          canCancel: true,
          expiresAt: receipt.expiresAt,
        };
        setState((s) => ({
          ...s,
          pending: null,
          manual: {
            ...s.manual,
            [packet.taskId]: [
              pending,
              ...(s.manual[packet.taskId] ?? []).filter(
                (v) => v.snapshot.requestId !== packet.operationId,
              ),
            ],
          },
        }));
      } else update({ pending: null }, start.scope);
      await load(packet.taskId, true);
      return receipt;
    },
    [api, base, load, update, invalidateDetail],
  );
  const command = useCallback(
    async (task: string, action: string, value: unknown = null, provided?: J) => {
      const start = live.current;
      const startingVisit = runVisit.current;
      if (!start.scope || writes.current || !start.workspace.canWriteState)
        throw Error("unlock_required");
      const requireRunState = () => {
        if (action !== "manual_intent") return;
        const gate = runGate.current;
        if (
          runVisit.current !== startingVisit ||
          live.current.selected?.taskId !== task ||
          gate.key !== start.selectedKey ||
          !gate.ready
        )
          throw Error("request_failed");
        if (gate.running) throw Error("operation_pending");
      };
      requireRunState();
      writes.current = true;
      update({ busy: true, error: "" }, start.scope);
      try {
        const existing = await start.workspace.loadTaskCenterPending(task);
        if (existing) {
          update({ pending: existing }, start.scope);
          throw Error("operation_pending");
        }
        const definition = provided && action !== "manual_intent" ? provided : api(base(task));
        const [current, history] = await Promise.all([
          definition,
          action === "manual_intent" ? api(base(task) + "/manual") : null,
        ]);
        requireRunState();
        if (history) {
          if (!Array.isArray(history.items)) throw Error("invalid_response");
          const items = history.items;
          setState((s) => ({ ...s, manual: { ...s.manual, [task]: items } }));
          // Another client may have started this task since its detail was opened.
          if (items.some((item: J) => item.aggregate?.hasActiveExecutors)) return;
        }
        const packet = await start.workspace.prepareTaskCenterControl({
          state: current,
          action,
          value,
        });
        update({ pending: packet }, start.scope);
        return await send(packet);
      } catch (e) {
        if (action !== "manual_intent" || runVisit.current === startingVisit)
          update({ error: error(e) }, start.scope);
        throw e;
      } finally {
        writes.current = false;
        update({ busy: false }, start.scope);
      }
    },
    [api, base, send, update],
  );
  const recover = useCallback(
    async (task: string, replay = false, abandon = false) => {
      const start = live.current;
      if (!start.scope || writes.current) return;
      writes.current = true;
      update({ busy: true, error: "" }, start.scope);
      try {
        const packet = await start.workspace.loadTaskCenterPending(task);
        if (!packet) return;
        update({ pending: packet }, start.scope);
        if (abandon) {
          const bytes = new TextEncoder().encode(
            packet.body.command.protected + "." + packet.body.command.payload,
          );
          const fp = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), (b) =>
            b.toString(16).padStart(2, "0"),
          ).join("");
          const outcome = await api(base(task) + `/operations/${packet.operationId}/cancel`, {
            method: "POST",
            json: { contractVersion: CONTRACT, fingerprint: fp },
          });
          await start.workspace.finishTaskCenterPending(task, outcome);
          update({ pending: null }, start.scope);
          await load(task, true);
          return;
        }
        if (replay) {
          await send(packet);
          return;
        }
        const data = await api(
          base(task) +
            (packet.action === "manual_intent"
              ? `/manual/${packet.operationId}`
              : `/operations/${packet.operationId}`),
        );
        await start.workspace.finishTaskCenterPending(
          task,
          packet.action === "manual_intent" ? data.receipt : data,
        );
        update({ pending: null }, start.scope);
        await load(task, true);
      } catch (e) {
        update({ error: error(e) }, start.scope);
      } finally {
        writes.current = false;
        update({ busy: false }, start.scope);
      }
    },
    [api, base, load, send, update],
  );
  const cancel = useCallback(
    async (task: string, intent: string) => {
      try {
        await api(base(task) + `/manual/${intent}/cancel`, {
          method: "POST",
          json: { contractVersion: CONTRACT },
        });
        await load(task, true);
      } catch (e) {
        update({ error: error(e) });
      }
    },
    [api, base, load, update],
  );
  const trashList = useCallback(
    async (more = false) => {
      const start = live.current;
      if (!start.scope) return;
      update({ loading: true, error: "" });
      try {
        const root = `/api/v3/task-center/${start.workspace.vault!.vaultId}/trash`;
        const page = await api(root + "/query", {
          method: "POST",
          json: {
            contractVersion: CONTRACT,
            cursor: more && state.scope === start.scope ? state.trashCursor : null,
          },
        });
        // Opportunistic bounded retirement, only after the service reports expiry.
        // Never schedule work, retire a recoverable row, or loop past review-required data.
        for (const row of page.items) {
          if (
            !row.canRestore &&
            row.cleanupState === "pending" &&
            row.definition?.purgeAfter * 1000 <= Date.now()
          ) {
            await api(base(row.taskId) + "/maintenance", {
              method: "POST",
              json: { contractVersion: CONTRACT },
            });
          }
        }
        const rows = await Promise.all(
          page.items.map(async (row: J) => ({
            ...row,
            title: row.envelope ? (await start.workspace.openTask(row.envelope)).name : null,
          })),
        );
        update(
          {
            trash: more ? [...state.trash, ...rows] : rows,
            trashCursor: page.nextCursor,
            loading: false,
          },
          start.scope,
        );
      } catch (e) {
        update({ loading: false, error: error(e) }, start.scope);
      }
    },
    [api, base, update, state.scope, state.trash, state.trashCursor],
  );
  useEffect(() => {
    for (const c of controllers.current) c.abort();
    reads.current.clear();
    generations.current.clear();
    runReceipts.current = new WeakMap();
    setRunRead(null);
    legacyCache.current = new WeakMap();
    combinedEvidence.current = new WeakMap();
    selectedHistories.current = new WeakMap();
    recordHeads.current.clear();
    setLegacy(null);
    setState({
      scope,
      enabled: false,
      capabilityState: "loading",
      loading: false,
      busy: false,
      error: "",
      detailFailure: null,
      detailLoading: null,
      records: {},
      manual: {},
      pending: null,
      trash: [],
      trashCursor: null,
    });
    return () => {
      for (const c of controllers.current) c.abort();
    };
  }, [scope, api, update, overview]);
  const capabilitiesReady = state.scope === scope && state.capabilityState === "ready";
  useEffect(() => {
    if (!scope || !active || capabilitiesReady) return;
    const control = new AbortController();
    const loadCapabilities = async () => {
      const snapshot = await overview?.acquireWithFallback(control.signal);
      if (
        control.signal.aborted ||
        live.current.scope !== scope ||
        (overview && (!live.current.active || document.visibilityState === "hidden"))
      )
        return;
      const v =
        snapshot?.data.capabilities ??
        (await api("/api/v3/task-center/capabilities", { signal: control.signal }));
      if (!control.signal.aborted)
        update({ enabled: v.enabled === true, capabilityState: "ready" }, scope);
    };
    void loadCapabilities().catch(() => {
      if (!control.signal.aborted) update({ capabilityState: "error" }, scope);
    });
    return () => control.abort();
  }, [scope, active, capabilitiesReady, api, update, overview]);
  const overviewReceipt = overview?.receipt;
  useEffect(() => {
    if (overviewReceipt && scope)
      update(
        { enabled: overviewReceipt.data.capabilities.enabled === true, capabilityState: "ready" },
        scope,
      );
  }, [scope, overviewReceipt, update]);
  useEffect(() => {
    if (scope && active && selected) void load(selected.taskId);
  }, [scope, active, selectedKey, selectedDetail, load]);
  useEffect(() => {
    if (!scope || !active) return;
    const tasks = Object.entries(state.manual)
      .filter(([, rows]) => rows.some((v) => v.aggregate?.hasActiveExecutors))
      .map(([task]) => task);
    if (!tasks.length) return;
    let stopped = false;
    const poll = async () => {
      if (stopped || document.visibilityState === "hidden") return;
      for (const task of tasks) {
        if (stopped || live.current.scope !== scope) break;
        const generation = generations.current.get(task);
        try {
          const data = await api(base(task) + "/manual");
          if (!Array.isArray(data.items)) throw Error("invalid_response");
          if (
            !stopped &&
            live.current.scope === scope &&
            generation === generations.current.get(task)
          )
            setState((s) => ({ ...s, manual: { ...s.manual, [task]: data.items } }));
        } catch (e) {
          if (
            !stopped &&
            live.current.scope === scope &&
            generation === generations.current.get(task) &&
            live.current.selected?.taskId === task &&
            error(e) !== "cancelled"
          ) {
            const currentVisit = runVisit.current;
            setRunRead((previous) =>
              previous?.visit === currentVisit ? { ...previous, status: "error" } : previous,
            );
          }
        }
      }
    };
    const timer = setInterval(() => void poll(), 5000);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [scope, active, state.manual, api, base, update]);
  const current = scope && state.scope === scope ? state : null;
  const task = selected?.taskId;
  const record =
    task &&
    current?.detailLoading !== selectedKey &&
    current?.detailFailure !== selectedKey &&
    recordHeads.current.get(task)?.key === selectedKey
      ? current?.records[task]
      : undefined;
  const needsLegacy = Boolean(
    active &&
    selected?.status === "active" &&
    selected.resourceBindings.length &&
    record &&
    !record.rules,
  );
  useEffect(() => {
    const vault = workspace.vault;
    if (!needsLegacy || !record || !selected || !vault || !scope) return;
    const previous = legacyCache.current.get(record);
    if (previous) {
      setLegacy({ key: selectedKey, record, value: ready(previous) });
      return;
    }
    const control = new AbortController();
    const current = () =>
      !control.signal.aborted && live.current.active && live.current.selectedKey === selectedKey;
    const options = { signal: control.signal, display: true };
    setLegacy({ key: selectedKey, record, value: { status: "loading", providers: [] } });
    async function read(meta: TaskMetadata, v: Vault, verified: J) {
      try {
        const combined = combinedEvidence.current.get(verified);
        if (combined && !combined.legacy) throw Error("invalid_response");
        const authority =
          combined?.legacy?.status === "ready"
            ? combined.legacy.data
            : await api(
                `/api/v2/persistent-content/${v.vaultId}/tasks/${meta.taskId}/authority`,
                options,
              );
        const id = await legacyConnection(authority, meta, v, auth.profile?.uid);
        if (!current()) return;
        const providers: string[] = [];
        if (id) {
          const receipt = overview?.receipt;
          const age = receipt ? Date.now() - receipt.at : Infinity;
          const cached =
            receipt &&
            receipt.scope === `${scope}:${v.version}` &&
            receipt.data.vaultId === v.vaultId &&
            age >= 0 &&
            age < 30000
              ? readReportProviders(receipt.data.connections, v.vaultId)[id]
              : undefined;
          const bundled = combined?.attribution;
          if (combined?.legacy?.status === "ready" && !bundled) throw Error("invalid_response");
          const provider =
            bundled?.status === "ready"
              ? readReportProviders(bundled.data, v.vaultId)[id]
              : (cached ??
                readReportProviders(
                  await api("/api/v2/persistent-connections", options),
                  v.vaultId,
                )[id]);
          if (!provider) throw Error("authorization_changed");
          providers.push(provider);
        }
        if (!current()) return;
        legacyCache.current.set(verified, providers);
        setLegacy({ key: selectedKey, record: verified, value: ready(providers) });
      } catch (e) {
        if (current())
          setLegacy({
            key: selectedKey,
            record: verified,
            value: { status: "error", providers: [] },
            refreshRecord: error(e) === "version_conflict",
          });
      }
    }
    void read(selected, vault, record);
    return () => control.abort();
  }, [scope, selectedKey, needsLegacy, record, attempt, api, overview, auth.profile?.uid]);
  // Dispatch the primary state and, when necessary, its original authority first.
  // Run history and the encrypted outbox govern actions, not executor presentation.
  const recordFailed = current?.detailFailure === selectedKey;
  const historySource =
    selectedDetail &&
    (recordFailed ||
      (record && combinedEvidence.current.get(record)?.selection === selectedDetail.id))
      ? selectedDetail
      : undefined;
  useEffect(() => {
    if (!active || !scope || !task || (!record && !recordFailed)) return;
    const control = new AbortController();
    const generation = generations.current.get(task);
    const valid = () =>
      !control.signal.aborted &&
      runVisit.current === visit &&
      generations.current.get(task) === generation;
    setRunRead(null);
    const readHistory = async () => {
      const at = record && runReceipts.current.get(record);
      const age = at === undefined ? Infinity : Date.now() - at;
      if (age >= 0 && age < 15000) return;
      const queued = historySource && selectedHistories.current.get(historySource);
      const data = await (queued ?? api(base(task) + "/manual", { signal: control.signal }));
      if (!Array.isArray(data.items)) throw Error("invalid_response");
      if (!valid()) return;
      if (queued && historySource) selectedHistories.current.delete(historySource);
      if (record) runReceipts.current.set(record, Date.now());
      setState((s) => ({ ...s, manual: { ...s.manual, [task]: data.items } }));
    };
    const readPending = async () => {
      const pending = await live.current.workspace.loadTaskCenterPending(task);
      if (valid() && !writes.current) update({ pending }, scope);
    };
    void Promise.all([readHistory(), readPending()]).then(
      () => {
        if (valid()) setRunRead({ visit, record, status: "ready" });
      },
      () => {
        if (valid()) setRunRead({ visit, record, status: "error" });
      },
    );
    return () => control.abort();
  }, [
    active,
    scope,
    visit,
    task,
    record,
    recordFailed,
    historySource,
    runAttempt,
    api,
    base,
    update,
  ]);
  const runState =
    active && runRead?.visit === visit && runRead.record === record ? runRead.status : "loading";
  runGate.current = {
    key: selectedKey,
    ready: runState === "ready" && Boolean(record),
    running: Boolean(
      task && current?.manual[task]?.some((item) => item.aggregate?.hasActiveExecutors),
    ),
  };
  const currentAssignments: J[] =
    selected?.status === "active" &&
    record?.rules?.definition.taskVersion === selected.taskVersion &&
    record.rules.definition.executionEpoch === selected.executionEpoch
      ? record.assignments.filter(
          (row: J) => row.assignment.status === "active" && row.plan?.currentAssignment,
        )
      : [];
  let executors: ExecutorDisplay = { status: "loading", providers: [] };
  if (current?.detailFailure === selectedKey) executors = { status: "error", providers: [] };
  else if (record && selected && current?.detailLoading !== selectedKey) {
    if (record.rules) executors = ready(currentAssignments.map((row) => row.assignment.provider));
    else if (!needsLegacy) executors = ready();
    else if (legacy?.key === selectedKey && legacy.record === record) executors = legacy.value;
  }
  const retryExecutors = () => {
    if (!active || !task) return;
    if (
      !record ||
      current?.detailFailure === selectedKey ||
      (legacy?.key === selectedKey && legacy.record === record && legacy.refreshRecord)
    )
      void load(task, true);
    else if (needsLegacy) setAttempt((previous) => previous + 1);
  };
  return {
    scope,
    enabled: current?.enabled ?? false,
    capabilityState: current?.capabilityState ?? "loading",
    loading: Boolean(current?.loading || (task && current?.detailLoading === selectedKey)),
    busy: current?.busy ?? false,
    error: current?.error ?? "",
    records: current?.records ?? {},
    selectedRecord: record,
    currentAssignments,
    executors,
    retryExecutors,
    runState,
    retryRunState: () => {
      if (historySource) selectedHistories.current.delete(historySource);
      if (record) runReceipts.current.delete(record);
      setRunAttempt((n) => n + 1);
    },
    manual: current?.manual ?? {},
    pending:
      current?.pending && (!task || current.pending.taskId === task) ? current.pending : null,
    trash: current?.trash ?? [],
    trashCursor: current?.trashCursor ?? null,
    load,
    command,
    recover,
    cancel,
    trashList,
    api,
    base,
  };
}
export type TaskCenterModel = ReturnType<typeof useTaskCenter>;
