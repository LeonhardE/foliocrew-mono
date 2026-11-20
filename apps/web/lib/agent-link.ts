import {
  BRANDED_AGENT_ORIGIN,
  ConnectionError,
  exact,
  isLegacyAgentOrigin,
} from "./agent-connections";

type AgentLinkFields = {
  enabled: boolean;
  hubOrigin: string | null;
};
export type AgentLinkConfiguration = AgentLinkFields &
  (
    | { schemaVersion: 1 }
    | {
        schemaVersion: 2;
        brandOrigin: typeof BRANDED_AGENT_ORIGIN | null;
        preferredOrigin: string | null;
      }
  );
export const AGENT_LINK_CONFIGURATION_PATH = "/api/private/agent-link/config?version=2";

export function readAgentLinkConfiguration(value: unknown): AgentLinkConfiguration {
  const v1 = exact(value, ["schemaVersion", "enabled", "hubOrigin"]) && value.schemaVersion === 1;
  const v2 =
    exact(value, ["schemaVersion", "enabled", "hubOrigin", "brandOrigin", "preferredOrigin"]) &&
    value.schemaVersion === 2;
  if (
    (!v1 && !v2) ||
    typeof value.enabled !== "boolean" ||
    (value.enabled
      ? !isLegacyAgentOrigin(value.hubOrigin) ||
        (v2 &&
          ((value.brandOrigin !== null && value.brandOrigin !== BRANDED_AGENT_ORIGIN) ||
            (value.preferredOrigin !== value.hubOrigin &&
              (value.brandOrigin === null || value.preferredOrigin !== value.brandOrigin))))
      : value.hubOrigin !== null ||
        (v2 && (value.brandOrigin !== null || value.preferredOrigin !== null)))
  )
    throw new ConnectionError("invalid_response");
  return value as AgentLinkConfiguration;
}

export async function loadAgentLinkConfiguration(
  signal?: AbortSignal,
): Promise<AgentLinkConfiguration> {
  const response = await fetch(AGENT_LINK_CONFIGURATION_PATH, {
    method: "GET",
    cache: "no-store",
    credentials: "omit",
    redirect: "error",
    referrerPolicy: "no-referrer",
    signal,
    headers: { Accept: "application/json" },
  });
  if (signal?.aborted) throw new ConnectionError("cancelled");
  if (
    response.status !== 200 ||
    response.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() !==
      "application/json" ||
    !response.body
  )
    throw new ConnectionError("invalid_response");
  const reader = response.body.getReader(),
    decoder = new TextDecoder("utf-8", { fatal: true });
  let text = "",
    size = 0;
  const cancel = () => {
    void reader.cancel().catch(() => {});
  };
  signal?.addEventListener("abort", cancel, { once: true });
  try {
    for (;;) {
      const part = await reader.read();
      if (signal?.aborted) throw new ConnectionError("cancelled");
      if (part.done) break;
      size += part.value.byteLength;
      if (size > 4096) throw new ConnectionError("invalid_response");
      text += decoder.decode(part.value, { stream: true });
    }
    text += decoder.decode();
    return readAgentLinkConfiguration(JSON.parse(text));
  } catch (error) {
    if (error instanceof ConnectionError) throw error;
    throw new ConnectionError("invalid_response");
  } finally {
    signal?.removeEventListener("abort", cancel);
    cancel();
    reader.releaseLock();
  }
}
