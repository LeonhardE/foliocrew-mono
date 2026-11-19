export const USER_RECOVERY_PROXY = "/api/private/user";
export const USER_RECOVERY_MAX_REQUEST = 4096;
export const RECOVERY_PROFILE = "folioview.owner-recovery-evidence.v1";
export const REGISTRY_PAGE_PROFILE = "folioview.owner-registry-page.v1";

export const RECOVERY_KEYS = [
  "contractVersion",
  "profile",
  "ownerSubject",
  "vaultId",
  "nonce",
  "deviceId",
  "deviceSigningKeyId",
  "deviceEncryptionKeyId",
];
export const REGISTRY_PAGE_KEYS = [
  "contractVersion",
  "profile",
  "ownerSubject",
  "vaultId",
  "base",
  "target",
];

const ROUTE =
  /^\/api\/v3\/private-resources\/vaults\/([A-Za-z0-9][A-Za-z0-9_-]{0,127})\/(recovery-evidence|registry-pages\/read)$/;

export function userRecoveryRoute(path: string) {
  const match = ROUTE.exec(path);
  if (!match || match[0] !== path) return null;
  const recovery = match[2] === "recovery-evidence";
  return {
    vault: match[1],
    profile: recovery ? RECOVERY_PROFILE : REGISTRY_PAGE_PROFILE,
    keys: recovery ? RECOVERY_KEYS : REGISTRY_PAGE_KEYS,
  };
}
