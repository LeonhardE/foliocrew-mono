export const USER_RECOVERY_PROXY = "/api/private/user";
export const USER_RECOVERY_MAX_REQUEST = 4096;
const MAX_HANDOVER_REQUEST = 131072 + 16384 + 256;
export const RECOVERY_PROFILE = "folioview.owner-recovery-evidence.v1";
export const REGISTRY_PAGE_PROFILE = "folioview.owner-registry-page.v1";
export const HANDOVER_CHECK_PROFILE = "folioview.owner-handover-check.v1";
export const HANDOVER_PROFILE = "folioview.owner-handover.v1";
export const REGISTRY_START_PROFILE = "folioview.owner-registry-start-evidence.v1";
export const REGISTRY_UPDATE_PROFILE = "folioview.owner-registry-update.v1";
export const HOLDINGS_REGISTRATION_PROFILE = "folioview.owner-holdings-registration.v1";
export const OWNER_CURRENT_PROFILE = "folioview.owner-current-user-vault.v1";
export const PRIVATE_DISPLAY_NAME_PROFILE = "folioview.private-display-name.v1";
export const USER_ARCHIVE_LIFECYCLE_PROFILE = "folioview.owner-user-archive-lifecycle.v1";
export const OWNER_CURRENT_PATH = "/api/v3/private-resources/vaults/current/read";

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
  "archive-lifecycle/read": {
    profile: USER_ARCHIVE_LIFECYCLE_PROFILE,
    keys: [...SCOPE, "nonce", "operationId"],
  },
  "registry/advance": {
    profile: REGISTRY_UPDATE_PROFILE,
    keys: [...SCOPE, "operationId", "expectedVaultVersion", "registryBundle"],
  },
  "display-names/read": {
    profile: PRIVATE_DISPLAY_NAME_PROFILE,
    keys: [...SCOPE, "sourceId", "operationId"],
  },
  "display-names/write": {
    profile: PRIVATE_DISPLAY_NAME_PROFILE,
    keys: [...SCOPE, "sourceId", "operationId", "command"],
  },
} as const;

const ROUTE =
  /^\/api\/v3\/private-resources\/vaults\/([A-Za-z0-9][A-Za-z0-9_-]{0,127})\/(recovery-evidence|registry-pages\/read|handover\/check|handover|registry-start\/read|registry\/advance|display-names\/(?:read|write)|archive-lifecycle\/read)$/;
const HOLDINGS_ROUTE =
  /^\/api\/v3\/private-resources\/vaults\/([A-Za-z0-9][A-Za-z0-9_-]{0,127})\/holdings-sources\/([A-Za-z0-9][A-Za-z0-9_-]{0,127})$/;

export function userRecoveryRoute(path: string) {
  if (path === OWNER_CURRENT_PATH)
    return {
      vault: null,
      source: null,
      profile: OWNER_CURRENT_PROFILE,
      keys: ["contractVersion", "profile", "ownerSubject", "nonce"],
      maxRequestBytes: USER_RECOVERY_MAX_REQUEST,
    };
  const holdings = HOLDINGS_ROUTE.exec(path);
  if (holdings?.[0] === path)
    return {
      vault: holdings[1],
      source: holdings[2],
      profile: HOLDINGS_REGISTRATION_PROFILE,
      keys: [...SCOPE, "sourceId", "operationId", "command"],
      maxRequestBytes: 65_536,
    };
  const match = ROUTE.exec(path);
  if (!match || match[0] !== path) return null;
  const name = match[2] as keyof typeof RULES;
  return {
    vault: match[1],
    source: null,
    profile: RULES[name].profile,
    keys: [...RULES[name].keys],
    maxRequestBytes:
      name === "handover"
        ? MAX_HANDOVER_REQUEST
        : name === "registry/advance"
          ? 131_072 + 2_048
          : name === "display-names/write"
            ? 12_288 + 2_048
            : USER_RECOVERY_MAX_REQUEST,
  };
}
