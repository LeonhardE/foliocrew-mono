import type { EncryptedTask } from "./encrypted-types";
import { encryptedTask, exact, identifier, object, TASK_CONTRACT } from "./task-types";
import { boundedJson, untilSignal } from "./workspace-cache";
import { readReportProviders } from "./report-provider-attribution";

type JsonObject = Record<string, any>;
type Section<T> = null | { status: "unavailable" } | { status: "ready"; data: T };
type Request = { contractVersion: string; includePacket: boolean; includeAttribution: boolean };
export type TaskDetailRead = {
  state: JsonObject;
  packet: Section<EncryptedTask>;
  legacy: Section<JsonObject>;
  attribution: Section<JsonObject>;
};
export function taskDetailRequest(value: unknown): value is Request {
  return (
    exact(value, ["contractVersion", "includePacket", "includeAttribution"]) &&
    value.contractVersion === TASK_CONTRACT &&
    typeof value.includePacket === "boolean" &&
    typeof value.includeAttribution === "boolean"
  );
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
  if (
    !exact(value, ["contractVersion", "profile", "state", "packet", "legacy", "attribution"]) ||
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
  return { state: value.state, packet, legacy, attribution };
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
): Promise<TaskDetailRead> {
  if (!identifier(vault) || !identifier(task)) throw Error("invalid_request");
  const options = { contractVersion: TASK_CONTRACT, includePacket, includeAttribution };
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
