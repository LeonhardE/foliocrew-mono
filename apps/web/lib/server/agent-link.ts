import "server-only";
import { BRANDED_AGENT_ORIGIN } from "../agent-connections";
import { hubConfiguration } from "./hub-owner";

/** A configured destination is not proof that Muse connection issuance is enabled. */
export function agentLinkConfiguration(env: NodeJS.ProcessEnv = process.env, version = 1) {
  const configuration = hubConfiguration(env);
  const current = {
    enabled: configuration !== null,
    hubOrigin: configuration?.origin ?? null,
  };
  if (version !== 2) return { schemaVersion: 1, ...current };
  const brandOrigin =
    current.enabled && env.FOLIOVIEW_AGENT_BRAND_ORIGIN === BRANDED_AGENT_ORIGIN
      ? BRANDED_AGENT_ORIGIN
      : null;
  return {
    schemaVersion: 2,
    ...current,
    brandOrigin,
    preferredOrigin:
      env.FOLIOVIEW_AGENT_PREFER_BRAND === "1" && brandOrigin ? brandOrigin : current.hubOrigin,
  };
}
