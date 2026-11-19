export const USER_RECOVERY_PROXY = "/api/private/user";
export const USER_RECOVERY_MAX_REQUEST = 4096;
const MAX_HANDOVER_REQUEST = 131072 + 16384 + 256;
export const RECOVERY_PROFILE = "folioview.owner-recovery-evidence.v1";
export const REGISTRY_PAGE_PROFILE = "folioview.owner-registry-page.v1";
export const HANDOVER_CHECK_PROFILE = "folioview.owner-handover-check.v1";
export const HANDOVER_PROFILE = "folioview.owner-handover.v1";
export const REGISTRY_START_PROFILE = "folioview.owner-registry-start-evidence.v1";

const SCOPE = ["contractVersion", "profile", "ownerSubject", "vaultId"];
export const RECOVERY_KEYS = [
  ...SCOPE,
  "nonce",
  "deviceId",
  "deviceSigningKeyId",
  "deviceEncryptionKeyId",
];
export const REGISTRY_PAGE_KEYS = [...SCOPE, "base", "target"];

const RULES = {
  "recovery-evidence": { profile: RECOVERY_PROFILE, keys: RECOVERY_KEYS },
  "registry-pages/read": { profile: REGISTRY_PAGE_PROFILE, keys: REGISTRY_PAGE_KEYS },
  "handover/check": { profile: HANDOVER_CHECK_PROFILE, keys: SCOPE },
  handover: {
    profile: HANDOVER_PROFILE,
    keys: [...SCOPE, "operationId", "signedTransition", "firstBundle"],
  },
  "registry-start/read": { profile: REGISTRY_START_PROFILE, keys: [...SCOPE, "nonce"] },
} as const;

const ROUTE =
  /^\/api\/v3\/private-resources\/vaults\/([A-Za-z0-9][A-Za-z0-9_-]{0,127})\/(recovery-evidence|registry-pages\/read|handover\/check|handover|registry-start\/read)$/;

export function userRecoveryRoute(path: string) {
  const match = ROUTE.exec(path);
  if (!match || match[0] !== path) return null;
  const name = match[2] as keyof typeof RULES;
  return {
    vault: match[1],
    profile: RULES[name].profile,
    keys: [...RULES[name].keys],
    maxRequestBytes: name === "handover" ? MAX_HANDOVER_REQUEST : USER_RECOVERY_MAX_REQUEST,
  };
}
