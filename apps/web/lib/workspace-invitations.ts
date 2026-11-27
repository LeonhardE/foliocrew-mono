export const WORKSPACE_INVITATIONS = "/api/private/invitations";
export const INVITATION_ID = /^[a-f0-9]{64}$/;
export const INVITATION_REVISION = /^[a-f0-9]{32}$/;
export const INVITATION_EMAIL = /^[a-z0-9]+(?:\.[a-z0-9]+)*@gmail\.com$/;

export const INVITATION_STATUSES = [
  "sending",
  "send_failed",
  "invited",
  "joined",
  "expired",
  "revoked",
] as const;

export type Invitation = {
  id: string;
  revision: string;
  email: string;
  status: (typeof INVITATION_STATUSES)[number];
  updatedAt: number;
  expiresAt: number;
  canRetry: boolean;
  canRevoke: boolean;
};

export type InvitationPage = {
  items: Invitation[];
  nextCursor: string | null;
};

export function invitationRoute(path: string, method: string) {
  if (!path.startsWith(WORKSPACE_INVITATIONS)) return null;
  const suffix = path.slice(WORKSPACE_INVITATIONS.length);
  if (method === "GET") {
    if (suffix === "" || suffix === "/capability" || /^\?after=[a-f0-9]{64}$/.test(suffix))
      return suffix;
  }
  if (method === "POST") {
    if (suffix === "" || /^\/[a-f0-9]{64}\/[a-f0-9]{32}\/(?:retry|revoke)$/.test(suffix))
      return suffix;
  }
  if (method === "DELETE" && /^\/[a-f0-9]{64}\/[a-f0-9]{32}$/.test(suffix)) return suffix;
  return null;
}
