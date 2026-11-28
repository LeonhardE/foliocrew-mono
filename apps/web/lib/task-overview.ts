import { metadataPage as retiredMetadataPage } from "./inbox-types";
/** Task-page display transport only; packets still require the existing Owner Worker. */
import type { EncryptedTask, TaskMetadata } from "./encrypted-types";
import {
  encryptedTask,
  exact,
  identifier,
  taskPage,
  taskPacketPage,
  sameTaskMetadata,
  TASK_CONTRACT,
  TaskError,
} from "./task-types";
import { resultPage } from "./task-result-reader";
import { readReportProviders } from "./report-provider-attribution";
import { boundedJson, untilSignal } from "./workspace-cache";
type J = Record<string, any>;
import {
  taskOverviewRequest,
  overviewPath,
  TASK_OVERVIEW_TIMEOUT_MS,
  type KnownTaskPacket,
} from "./task-overview-request";
export function overviewPacketIds(tasks: J[], known: KnownTaskPacket[], preferredTaskId?: string) {
  const preferred = tasks.find((row) => row.taskId === preferredTaskId);
  const remaining = tasks
    .filter(
      (t) =>
        t !== preferred &&
        !known.some(
          (k) =>
            k.taskId === t.taskId &&
            k.taskVersion === t.taskVersion &&
            k.envelopeFingerprint === t.envelopeFingerprint,
        ),
    )
    .slice(0, preferred ? 3 : 4)
    .map((t) => t.taskId as string);
  return preferred ? [preferred.taskId as string, ...remaining] : remaining;
}
export type TaskOverview = {
  contractVersion: string;
  profile: string;
  vaultId: string;
  tasks: J;
  capabilities: J;
  feeds: { persistent: J; foreground?: J; archived?: J };
  connections: J;
  packets: J | null;
};
export function parseTaskOverview(
  v: unknown,
  vault: string,
  known: KnownTaskPacket[],
  packetLimit: 0 | 4 = 4,
  preferredTaskId?: string,
): TaskOverview {
  if (
    !exact(v, [
      "contractVersion",
      "profile",
      "vaultId",
      "tasks",
      "capabilities",
      "feeds",
      "connections",
      "packets",
    ]) ||
    v.contractVersion !== TASK_CONTRACT ||
    v.profile !== "folioview.owner-task-overview.v1" ||
    v.vaultId !== vault ||
    !identifier(vault) ||
    (!exact(v.feeds, ["persistent"]) && !exact(v.feeds, ["persistent", "foreground", "archived"]))
  )
    throw Error("invalid_response");
  const tasks = taskPage(v.tasks);
  if (tasks.some((t) => t.vaultId !== vault)) throw Error("invalid_response");
  const c = v.capabilities;
  if (
    !exact(c, [
      "contractVersion",
      "profile",
      "enabled",
      "actions",
      "dispatchSupported",
      "nativeScheduleAttested",
    ]) ||
    c.contractVersion !== TASK_CONTRACT ||
    c.profile !== "folioview.task-center.v1" ||
    typeof c.enabled !== "boolean" ||
    JSON.stringify(c.actions) !==
      JSON.stringify([
        "set_rules",
        "set_assignment",
        "remove_assignment",
        "trash",
        "restore",
        "purge",
      ]) ||
    c.dispatchSupported !== false ||
    c.nativeScheduleAttested !== false
  )
    throw Error("invalid_response");
  resultPage(v.feeds.persistent);
  if ("foreground" in v.feeds) {
    retiredMetadataPage(v.feeds.foreground);
    retiredMetadataPage(v.feeds.archived);
  }
  readReportProviders(v.connections, vault);
  const ids = packetLimit === 4 ? overviewPacketIds(tasks, known, preferredTaskId) : [];
  if (v.packets !== null) {
    if (!ids.length) throw Error("invalid_response");
    const p = taskPacketPage(v.packets, ids);
    if (
      p.items.some(
        (row) =>
          row.status === "ready" &&
          !sameTaskMetadata(
            row.packet.metadata,
            tasks.find((t) => t.taskId === row.taskId)!,
          ),
      )
    )
      throw Error("invalid_response");
  }
  return v as TaskOverview;
}
function freezeDisplay<T>(value: T): T {
  if (value && typeof value === "object") {
    for (const child of Object.values(value)) freezeDisplay(child);
    Object.freeze(value);
  }
  return value;
}
export type OverviewReceipt = {
  data: TaskOverview;
  at: number;
  serial: number;
  scope: string;
  preferredTaskId?: string;
};
type Config = {
  scope: string | null;
  vault: string | null;
  active: boolean;
  visible: boolean;
  preferredTaskId?: string;
  known: () => KnownTaskPacket[];
  send: (path: string, options: any) => Promise<Response>;
};

class OverviewUnavailable extends Error {}

/** One page-local shared read; no Worker, permission or cross-session cache. */
export class TaskOverviewRead {
  private config: Config | null = null;
  private cached: OverviewReceipt | null = null;
  private pending: {
    promise: Promise<OverviewReceipt>;
    controller: AbortController;
    users: number;
    epoch: number;
    preferredTaskId?: string;
  } | null = null;
  private running = new Set<{ controller: AbortController }>();
  private preferredSupported = true;
  private epoch = 0;
  private serial = 0;
  error = "";
  constructor(
    private changed: () => void,
    private now = Date.now,
  ) {}
  configure(next: Config) {
    if (this.config?.scope !== next.scope) {
      this.invalidate();
      this.preferredSupported = true;
      this.cached = null;
      this.error = "";
    }
    if (!next.active || !next.visible) for (const row of this.running) row.controller.abort();
    this.config = next;
  }
  get receipt() {
    const r = this.cached;
    return r && r.scope === this.config?.scope ? r : null;
  }
  currentTaskPacket(metadata: TaskMetadata) {
    const receipt = this.receipt;
    if (!receipt || !this.config?.active || !this.config.visible) return null;
    const age = this.now() - receipt.at;
    if (age < 0 || age >= 30_000) return null;
    const row = receipt.data.packets?.items.find((item: J) => item.taskId === metadata.taskId);
    if (row?.status !== "ready" || !sameTaskMetadata(row.packet.metadata, metadata)) return null;
    return { packet: encryptedTask(row.packet), at: receipt.at };
  }
  prefersTask(taskId: string) {
    if (this.pending) return this.pending.preferredTaskId === taskId;
    if (this.receipt) {
      const age = this.now() - this.receipt.at;
      if (age >= 0 && age < 30_000) return this.receipt.preferredTaskId === taskId;
    }
    return !this.error && this.config?.preferredTaskId === taskId;
  }
  async linkedTaskPacket(
    taskId: string,
    signal: AbortSignal,
    readHead: () => Promise<EncryptedTask>,
  ) {
    const find = () => {
      const metadata = this.receipt?.data.tasks.items.find(
        (item: TaskMetadata) => item.taskId === taskId,
      );
      return metadata ? this.currentTaskPacket(metadata) : null;
    };
    let direct: Promise<{ packet: EncryptedTask; at?: number }> | undefined;
    const original = () =>
      (direct ??= Promise.resolve().then(async () => {
        if (signal.aborted) throw new TaskError("cancelled");
        return { packet: await readHead() };
      }));
    const receipt = this.receipt;
    if (receipt && this.now() - receipt.at >= 0 && this.now() - receipt.at < 30_000)
      return find() ?? original();
    if (!this.prefersTask(taskId)) return original();

    // A slow list can still win after the independent task read begins.
    const control = new AbortController();
    const stop = () => control.abort();
    signal.addEventListener("abort", stop, { once: true });
    if (signal.aborted) stop();
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const primary = this.acquire(control.signal).then(
        () => find() ?? original(),
        () => original(),
      );
      const slow = new Promise<Awaited<ReturnType<typeof original>>>((resolve) => {
        timer = setTimeout(() => resolve(original()), 10_000);
      });
      const fallback = slow.catch((error) => {
        if (
          error instanceof TaskError &&
          ["network_unavailable", "source_unavailable", "service_busy", "request_timeout"].includes(
            error.code,
          )
        )
          return primary;
        throw error;
      });
      return await untilSignal(Promise.race([primary, fallback]), signal);
    } finally {
      clearTimeout(timer);
      signal.removeEventListener("abort", stop);
      stop();
    }
  }
  invalidate(abort = true) {
    this.epoch++;
    this.cached = null;
    if (abort) for (const row of this.running) row.controller.abort();
    this.pending = null;
  }
  async acquireWithFallback(signal?: AbortSignal): Promise<OverviewReceipt | null> {
    try {
      return await this.acquire(signal);
    } catch (error) {
      if (error instanceof OverviewUnavailable && !signal?.aborted) return null;
      throw error;
    }
  }
  async acquire(signal?: AbortSignal): Promise<OverviewReceipt> {
    const start = this.config;
    if (!start?.scope || !start.vault || !start.active || !start.visible || signal?.aborted)
      throw Error("cancelled");
    const age = this.cached ? this.now() - this.cached.at : -1;
    if (this.cached && age >= 0 && age < 30000)
      return untilSignal(Promise.resolve(this.cached), signal);
    if (this.pending?.controller.signal.aborted) this.pending = null;
    if (!this.pending) {
      const controller = new AbortController(),
        epoch = this.epoch;
      const entry = {
        controller,
        epoch,
        preferredTaskId: this.preferredSupported ? start.preferredTaskId : undefined,
        users: 0,
        promise: Promise.resolve(null as unknown as OverviewReceipt),
      };
      this.pending = entry;
      this.running.add(entry);
      this.error = "";
      entry.promise = Promise.resolve().then(async () => {
        let timeout = false;
        const timer = setTimeout(() => {
          timeout = true;
          controller.abort();
        }, TASK_OVERVIEW_TIMEOUT_MS);
        const cancelled = () => new TaskError(timeout ? "request_timeout" : "cancelled");
        const check = () => {
          if (
            controller.signal.aborted ||
            this.config?.scope !== start.scope ||
            !this.config.active ||
            !this.config.visible
          )
            throw cancelled();
        };
        try {
          const known = structuredClone(start.known());
          const fetchOverview = (preferredTaskId?: string) => {
            const body = {
              ...(preferredTaskId && { preferredTaskId }),
              contractVersion: TASK_CONTRACT,
              knownPacketVersions: known,
              packetLimit: 4,
            };
            if (!taskOverviewRequest(body)) throw Error("invalid_response");
            return untilSignal(
              start.send(overviewPath(start.vault!), {
                method: "POST",
                json: body,
                signal: controller.signal,
                headers: { "X-FolioView-Contract": TASK_CONTRACT },
              }),
              controller.signal,
              cancelled,
            );
          };
          let preferred = entry.preferredTaskId;
          let response = await fetchOverview(preferred);
          check();
          if (preferred && [400, 422].includes(response.status)) {
            void response.body?.cancel().catch(() => {});
            if (this.epoch === epoch) this.preferredSupported = false;
            preferred = undefined;
            response = await fetchOverview();
            check();
          }
          if (!response.ok) {
            void response.body?.cancel().catch(() => {});
            if (response.status === 503) throw new OverviewUnavailable("service_unavailable");
            throw Error(response.status >= 500 ? "service_unavailable" : "request_failed");
          }
          const raw = await boundedJson(response, 1048576, controller.signal, cancelled);
          check();
          const data = freezeDisplay(parseTaskOverview(raw, start.vault!, known, 4, preferred));
          check();
          const receipt = {
            data,
            at: this.now(),
            serial: ++this.serial,
            scope: start.scope!,
            preferredTaskId: preferred,
          };
          if (this.epoch === epoch) {
            this.cached = receipt;
            this.changed();
          }
          return receipt;
        } catch (e) {
          if (
            this.epoch === epoch &&
            this.config?.scope === start.scope &&
            !controller.signal.aborted
          ) {
            this.error = e instanceof Error ? e.message : "request_failed";
            this.changed();
          }
          throw e;
        } finally {
          clearTimeout(timer);
          this.running.delete(entry);
          if (this.pending === entry) this.pending = null;
        }
      });
    }
    const entry = this.pending;
    entry.users++;
    try {
      return await untilSignal(entry.promise, signal);
    } finally {
      if (--entry.users === 0 && this.running.has(entry)) entry.controller.abort();
    }
  }
}
