import "server-only";

import { hubConfiguration } from "./hub-owner";
import { portfolioConfiguration } from "./portfolio-owner";

export function ownerCapabilities(env: NodeJS.ProcessEnv = process.env) {
  return {
    schemaVersion: 1,
    flags: {
      portfolio: portfolioConfiguration(env) !== null,
      agentHub: hubConfiguration(env) !== null,
      ...(env.FOLIOVIEW_USER_OWNER_ENABLED === "true" &&
      /^[a-f0-9]{64}$/.test(env.FOLIOVIEW_USER_CURRENT_OWNER ?? "")
        ? { userVault: true }
        : {}),
    },
  };
}
