type J = Record<string, any>;
import { exact, identifier, object, TASK_CONTRACT } from "./task-types";
export type KnownTaskPacket = { taskId: string; taskVersion: number; envelopeFingerprint: string };
// Allow one cold Owner verification and composition. The browser also needs queue and transfer time.
export const TASK_OVERVIEW_PROXY_MS = 20_000;
export const TASK_OVERVIEW_TIMEOUT_MS = TASK_OVERVIEW_PROXY_MS + 4_000;
export const overviewPath = (vault: string) => `/api/v3/tasks/${vault}/overview/query`;
export function taskOverviewRequest(v: unknown): v is {
  contractVersion: string;
  knownPacketVersions: KnownTaskPacket[];
  packetLimit: 0 | 4;
  preferredTaskId?: string;
} {
  const keys = ["contractVersion", "knownPacketVersions", "packetLimit"];
  if (object(v) && Object.hasOwn(v, "preferredTaskId")) {
    if (v.packetLimit !== 4 || !identifier(v.preferredTaskId)) return false;
    keys.push("preferredTaskId");
  }
  return (
    exact(v, keys) &&
    v.contractVersion === TASK_CONTRACT &&
    [0, 4].includes(v.packetLimit) &&
    Array.isArray(v.knownPacketVersions) &&
    v.knownPacketVersions.length <= 32 &&
    new Set(v.knownPacketVersions.map((k: J) => k?.taskId)).size === v.knownPacketVersions.length &&
    v.knownPacketVersions.every(
      (k: unknown) =>
        exact(k, ["taskId", "taskVersion", "envelopeFingerprint"]) &&
        identifier(k.taskId) &&
        Number.isSafeInteger(k.taskVersion) &&
        k.taskVersion >= 1 &&
        k.taskVersion <= 50 &&
        typeof k.envelopeFingerprint === "string" &&
        /^[a-f0-9]{64}$/.test(k.envelopeFingerprint),
    )
  );
}
