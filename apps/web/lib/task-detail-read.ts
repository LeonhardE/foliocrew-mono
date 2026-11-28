import type { EncryptedTask, TaskMetadata } from "./encrypted-types";
import {
  encryptedTask,
  exact,
  identifier,
  object,
  taskMetadata,
  sameTaskMetadata,
  TASK_CONTRACT,
} from "./task-types";
import { boundedJson, untilSignal } from "./workspace-cache";
import { readReportProviders } from "./report-provider-attribution";

type JsonObject = Record<string, any>;
type Section<T> = null | { status: "unavailable" } | { status: "ready"; data: T };
type Request = {
  contractVersion: string;
  includePacket: boolean;
  includeAttribution: boolean;
  includeVault?: true;
};
export type TaskDetailRead = {
  state: JsonObject;
  taskMetadata?: TaskMetadata;
  vaultResponse?: Exclude<Section<JsonObject>, null>;
  packet: Section<EncryptedTask>;
  legacy: Section<JsonObject>;
  attribution: Section<JsonObject>;
};
export function taskDetailRequest(value: unknown): value is Request {
  const keys = ["contractVersion", "includePacket", "includeAttribution"];
  if (object(value) && value.includeVault === true) keys.push("includeVault");
  return (
    exact(value, keys) &&
    value.contractVersion === TASK_CONTRACT &&
    typeof value.includePacket === "boolean" &&
    typeof value.includeAttribution === "boolean"
  );
}
export const TASK_CONTROLS_REQUEST = Object.freeze({
  contractVersion: TASK_CONTRACT,
  includePacket: false,
  includeAttribution: false,
  includeManual: true,
});
export function taskControlsRequest(value: unknown) {
  return (
    exact(value, Object.keys(TASK_CONTROLS_REQUEST)) &&
    Object.entries(TASK_CONTROLS_REQUEST).every(([key, expected]) => value[key] === expected)
  );
}

const stages = [
  "waiting",
  "running",
  "awaiting_confirmation",
  "result_received",
  "failed",
  "cancelled",
];
const activeStages = ["waiting", "running", "awaiting_confirmation"];
function manualSummary(value: unknown, vault: string, task: string, owner?: string) {
  if (
    !exact(value, [
      "snapshot",
      "aggregate",
      "reasons",
      "expiresAt",
      "canCancel",
      "dispatchSupported",
      "continuation",
      "nativeScheduleAttested",
    ]) ||
    value.dispatchSupported !== false ||
    value.nativeScheduleAttested !== false ||
    value.continuation !== "open_agent" ||
    typeof value.canCancel !== "boolean" ||
    !Number.isSafeInteger(value.expiresAt) ||
    !object(value.reasons)
  )
    return false;
  const { snapshot, aggregate } = value;
  if (
    !exact(snapshot, [
      "contractVersion",
      "profile",
      "ownerSubject",
      "vaultId",
      "taskId",
      "requestId",
      "requestedAt",
      "executors",
    ]) ||
    snapshot.contractVersion !== TASK_CONTRACT ||
    snapshot.profile !== "folioview.task-center.v1" ||
    snapshot.taskId !== task ||
    snapshot.vaultId !== vault ||
    !identifier(snapshot.ownerSubject) ||
    (owner !== undefined && snapshot.ownerSubject !== owner) ||
    typeof snapshot.requestId !== "string" ||
    !/^[A-Za-z0-9_-]{22,128}$/.test(snapshot.requestId) ||
    !Number.isSafeInteger(snapshot.requestedAt) ||
    snapshot.requestedAt < 0 ||
    !Array.isArray(snapshot.executors) ||
    snapshot.executors.length > 32 ||
    !exact(aggregate, ["state", "hasActiveExecutors", "counts"]) ||
    !exact(aggregate.counts, stages) ||
    ![...stages, "idle", "partial_failure"].includes(aggregate.state)
  )
    return false;
  const counts: Record<string, number> = {};
  const ids = new Set<string>();
  for (const row of snapshot.executors) {
    if (
      !exact(row, ["assignmentId", "assignmentVersion", "runId", "resultId", "stage"]) ||
      !identifier(row.assignmentId) ||
      ids.has(row.assignmentId) ||
      !Number.isSafeInteger(row.assignmentVersion) ||
      row.assignmentVersion < 1 ||
      !stages.includes(row.stage) ||
      (row.runId !== null && !identifier(row.runId)) ||
      (row.resultId !== null && !identifier(row.resultId))
    )
      return false;
    ids.add(row.assignmentId);
    counts[row.stage] = (counts[row.stage] ?? 0) + 1;
  }
  return (
    stages.every((stage) => aggregate.counts[stage] === (counts[stage] ?? 0)) &&
    aggregate.hasActiveExecutors === activeStages.some((stage) => counts[stage] > 0) &&
    Object.entries(value.reasons).every(
      ([key, reason]) => ids.has(key) && typeof reason === "string",
    )
  );
}
export function parseTaskControls(value: unknown, vault: string, task: string, owner?: string) {
  if (
    !exact(value, ["contractVersion", "profile", "state", "manual"]) ||
    value.contractVersion !== TASK_CONTRACT ||
    value.profile !== "folioview.owner-task-detail.v1" ||
    !object(value.state) ||
    value.state.taskId !== task ||
    value.state.contractVersion !== TASK_CONTRACT ||
    value.state.profile !== "folioview.task-center.v1" ||
    !exact(value.manual, ["contractVersion", "items"]) ||
    value.manual.contractVersion !== TASK_CONTRACT ||
    !Array.isArray(value.manual.items) ||
    value.manual.items.length > 16 ||
    !value.manual.items.every((row: unknown) => manualSummary(row, vault, task, owner)) ||
    new Set(value.manual.items.map((row: JsonObject) => row.snapshot.requestId)).size !==
      value.manual.items.length
  )
    throw Error("invalid_response");
  return { state: value.state, manual: value.manual };
}
function section<T>(value: unknown, parse: (data: unknown) => T): Section<T> {
  if (value === null) return null;
  if (exact(value, ["status"]) && value.status === "unavailable") return { status: "unavailable" };
  if (!exact(value, ["status", "data"]) || value.status !== "ready")
    throw Error("invalid_response");
  return { status: "ready", data: parse(value.data) };
}
export function parseTaskDetail(
  value: unknown,
  vault: string,
  task: string,
  options: Request,
): TaskDetailRead {
  const fields = ["contractVersion", "profile", "state", "packet", "legacy", "attribution"];
  if (options.includeVault) fields.push("taskMetadata", "vaultResponse");
  if (
    !exact(value, fields) ||
    value.contractVersion !== TASK_CONTRACT ||
    value.profile !== "folioview.owner-task-detail.v1" ||
    !object(value.state) ||
    value.state.taskId !== task ||
    value.state.contractVersion !== TASK_CONTRACT ||
    value.state.profile !== "folioview.task-center.v1" ||
    (!options.includePacket && value.packet !== null) ||
    (options.includePacket && value.packet === null) ||
    (!options.includeAttribution && value.attribution !== null) ||
    (value.state.rules !== null && value.legacy !== null)
  )
    throw Error("invalid_response");
  const packet = section(value.packet, (raw) => {
    const p = encryptedTask(raw);
    if (
      p.metadata.vaultId !== vault ||
      p.metadata.taskId !== task ||
      p.metadata.taskVersion !== value.state.taskVersion ||
      p.metadata.executionEpoch !== value.state.executionEpoch
    )
      throw Error("invalid_response");
    return p;
  });
  const legacy = section(value.legacy, (raw) => {
    if (
      !exact(raw, ["contractVersion", "profile", "authority", "envelope"]) ||
      raw.contractVersion !== TASK_CONTRACT ||
      raw.profile !== "folioview.persistent-content.v1" ||
      (raw.authority === null) !== (raw.envelope === null)
    )
      throw Error("invalid_response");
    if (raw.authority !== null) {
      const c = raw.authority?.context;
      if (
        !object(c) ||
        c.vaultId !== vault ||
        c.taskId !== task ||
        c.objectId !== task ||
        c.objectType !== "task" ||
        !identifier(c.connectionId)
      )
        throw Error("invalid_response");
    }
    return raw;
  });
  if (value.attribution !== null && !(legacy?.status === "ready" && legacy.data.authority))
    throw Error("invalid_response");
  const attribution = section(value.attribution, (raw) => {
    const connection = legacy?.status === "ready" && legacy.data.authority?.context?.connectionId;
    if (
      !object(raw) ||
      !connection ||
      raw.connections?.length !== 1 ||
      !Object.hasOwn(readReportProviders(raw, vault), connection)
    )
      throw Error("invalid_response");
    return raw;
  });
  const detail = { state: value.state, packet, legacy, attribution };
  if (!options.includeVault) return detail;
  const metadata = taskMetadata(value.taskMetadata);
  if (
    metadata.vaultId !== vault ||
    metadata.taskId !== task ||
    metadata.taskVersion !== value.state.taskVersion ||
    metadata.executionEpoch !== value.state.executionEpoch ||
    (packet?.status === "ready" && !sameTaskMetadata(packet.data.metadata, metadata))
  )
    throw Error("invalid_response");
  const vaultResponse = section(value.vaultResponse, (raw) => {
    if (
      !exact(raw, ["contractVersion", "vault", "sources"]) ||
      raw.contractVersion !== TASK_CONTRACT ||
      raw.vault?.vaultId !== vault ||
      !Array.isArray(raw.sources)
    )
      throw Error("invalid_response");
    return raw;
  });
  if (!vaultResponse) throw Error("invalid_response");
  return { ...detail, taskMetadata: metadata, vaultResponse };
}
export async function readTaskDetail(
  send: (
    path: string,
    options: { method: "POST"; json: Request; signal: AbortSignal },
  ) => Promise<Response>,
  vault: string,
  task: string,
  includePacket: boolean,
  includeAttribution: boolean,
  signal: AbortSignal,
  includeVault = false,
): Promise<TaskDetailRead> {
  if (!identifier(vault) || !identifier(task)) throw Error("invalid_request");
  const options: Request = {
    contractVersion: TASK_CONTRACT,
    includePacket,
    includeAttribution,
    ...(includeVault ? { includeVault: true } : {}),
  };
  const response = await untilSignal(
    send(`/api/v3/task-center/${vault}/tasks/${task}/detail/query`, {
      method: "POST",
      json: options,
      signal,
    }),
    signal,
  );
  if (!response.ok) {
    void response.body?.cancel().catch(() => {});
    throw Error(
      response.status === 404
        ? "not_found"
        : response.status >= 500
          ? "service_unavailable"
          : "request_failed",
    );
  }
  return parseTaskDetail(await boundedJson(response, 1048576, signal), vault, task, options);
}
