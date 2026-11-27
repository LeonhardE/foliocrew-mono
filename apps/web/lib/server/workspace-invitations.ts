import "server-only";

import {
  INVITATION_EMAIL,
  INVITATION_ID,
  INVITATION_REVISION,
  INVITATION_STATUSES,
  invitationRoute,
} from "@/lib/workspace-invitations";
import {
  JWT,
  Failure,
  bytes,
  createEdgeOriginVerifier,
  createFirebaseVerifier,
  errorResponse,
  fail,
  fields,
  integer,
  json,
  requireSameOrigin,
  until,
  type Options,
} from "./owner-transport";

const USER_PATH = "/api/v1/workspace-invitations";
const USER_ORIGIN = /^https:\/\/user-api-[0-9]{1,20}\.[a-z]+(?:-[a-z0-9]+)+[0-9]\.run\.app$/;
const PROJECT = /^[a-z][a-z0-9-]{4,28}[a-z0-9]$/;
const RESPONSE_ERRORS = new Map([
  [401, "invalid_token"],
  [403, "insufficient_scope"],
  [404, "not_found"],
  [409, "version_conflict"],
  [413, "payload_too_large"],
  [415, "unsupported_media_type"],
  [422, "invalid_envelope"],
]);

function matches(value: unknown, pattern: RegExp) {
  return typeof value === "string" && pattern.test(value);
}

function invite(value: unknown): boolean {
  return (
    fields(value, [
      "id",
      "revision",
      "email",
      "status",
      "updatedAt",
      "expiresAt",
      "canRetry",
      "canRevoke",
    ]) &&
    matches(value.id, INVITATION_ID) &&
    matches(value.revision, INVITATION_REVISION) &&
    matches(value.email, INVITATION_EMAIL) &&
    INVITATION_STATUSES.some((status) => status === value.status) &&
    integer(value.updatedAt, 0) &&
    integer(value.expiresAt, 0) &&
    typeof value.canRetry === "boolean" &&
    typeof value.canRevoke === "boolean"
  );
}

function validReply(value: unknown, suffix: string, method: string): boolean {
  if (suffix === "/capability") {
    return (
      fields(value, ["canManageInvitations"]) && typeof value.canManageInvitations === "boolean"
    );
  }
  if (method === "POST") return invite(value);
  return (
    fields(value, ["items", "nextCursor"]) &&
    (value.nextCursor === null || matches(value.nextCursor, INVITATION_ID)) &&
    Array.isArray(value.items) &&
    value.items.length <= 50 &&
    value.items.every(invite)
  );
}

export function createWorkspaceInvitationsProxy(options: Options = {}) {
  const env = options.env ?? process.env;
  const send = options.fetch ?? fetch;
  const now = options.now ?? Date.now;
  const edgeOrigin = createEdgeOriginVerifier(env, now);
  const verify = createFirebaseVerifier(send, now);

  return async function workspaceInvitationsProxy(request: Request) {
    if (env.FOLIOCREW_INVITATION_UI_ENABLED !== "1") return errorResponse("not_found");
    try {
      const origin = env.FOLIOVIEW_USER_ORIGIN ?? "";
      const project = env.FOLIOVIEW_OWNER_FIREBASE_PROJECT_ID ?? "";
      if (!USER_ORIGIN.test(origin) || new URL(origin).origin !== origin || !PROJECT.test(project))
        fail("authorization_unavailable");
      const url = new URL(request.url);
      const path = url.pathname + url.search;
      if (/[\\%#]/.test(request.url) || (request.url.includes("?") && !url.search)) fail();
      const suffix = invitationRoute(path, request.method);
      if (suffix === null) return errorResponse("not_found");
      requireSameOrigin(request, url, edgeOrigin);
      const authorization = request.headers.get("authorization") ?? "";
      if (
        authorization.length > 8192 ||
        !authorization.startsWith("Bearer ") ||
        !JWT.test(authorization.slice(7))
      )
        fail("invalid_token");

      const signal = AbortSignal.any([
        request.signal,
        AbortSignal.timeout(options.deadlineMs ?? 15000),
      ]);
      const raw = await bytes(request.body, 512, signal);
      const createsInvitation = request.method === "POST" && suffix === "";
      if (createsInvitation) {
        if (
          request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !==
          "application/json"
        )
          fail("unsupported_media_type");
        const value = json(raw);
        if (
          !(fields(value, ["email"]) || fields(value, ["email", "replaceRevision"])) ||
          typeof value.email !== "string" ||
          value.email.length > 74 ||
          !matches(value.email.trim().toLowerCase(), INVITATION_EMAIL) ||
          (Object.hasOwn(value, "replaceRevision") &&
            !matches(value.replaceRevision, INVITATION_REVISION))
        )
          fail("invalid_envelope");
      } else if (raw.byteLength !== 0) {
        fail();
      }
      await verify(authorization.slice(7), project, signal);
      const response = await until(
        send(origin + USER_PATH + suffix, {
          method: request.method,
          headers: {
            Authorization: authorization,
            ...(createsInvitation ? { "Content-Type": "application/json" } : {}),
          },
          ...(createsInvitation ? { body: Buffer.from(raw) } : {}),
          cache: "no-store",
          redirect: "error",
          signal,
        }),
        signal,
      );
      if (request.method === "DELETE" && response.status === 204)
        return new Response(null, { status: 204, headers: { "Cache-Control": "no-store" } });
      if (response.status !== 200 || request.method === "DELETE") {
        void response.body?.cancel().catch(() => {});
        return errorResponse(RESPONSE_ERRORS.get(response.status) ?? "source_unavailable");
      }
      const value = json(await bytes(response.body, 24_000, signal));
      if (!validReply(value, suffix, request.method)) return errorResponse("source_unavailable");
      return Response.json(value, { headers: { "Cache-Control": "no-store" } });
    } catch (error) {
      return errorResponse(error instanceof Failure ? error.code : "source_unavailable");
    }
  };
}

export const workspaceInvitationsProxy = createWorkspaceInvitationsProxy();
