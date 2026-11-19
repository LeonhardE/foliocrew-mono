import "server-only";
import {
  holdingsViewRequest,
  parseHoldingsView,
  type HoldingsViewExpected,
} from "../holdings-view";
import { cancellationRequest, cancellationResponse } from "./upload-cancellation";

import {
  CONTRACT,
  JWT,
  Failure,
  fail,
  requireSameOrigin,
  createEdgeOriginVerifier,
  record,
  fields,
  integer,
  errorResponse,
  until,
  bytes,
  json,
  carrier,
  signedObject,
  createFirebaseVerifier,
  createCloudRunIdentity,
  forwardResponse,
  proxyClock,
  timeProxyResponse,
  type Options,
} from "./owner-transport";

const PREFIX = "/api/private/portfolio";
const ID = "[A-Za-z0-9][A-Za-z0-9_-]{0,127}";
const OPERATION = "[A-Za-z0-9_-]{22,128}";
const SOURCE = `/api/v2/holdings/sources/${ID}`;
type Config = { project: string; origin: string; audience: string };
type Rule = {
  kind:
    | "view"
    | "read"
    | "snapshot"
    | "mutation"
    | "authority"
    | "synchronize"
    | "revision"
    | "cancellation";
  max: number;
  cancel?: { slot: string; id?: string };
};
export function portfolioConfiguration(env: NodeJS.ProcessEnv): Config | null {
  const project = env.FOLIOVIEW_OWNER_FIREBASE_PROJECT_ID ?? "";
  const origin = env.FOLIOVIEW_PORTFOLIO_ORIGIN ?? "";
  if (
    env.FOLIOVIEW_PORTFOLIO_OWNER_ENABLED !== "true" ||
    !/^[a-z][a-z0-9-]{4,28}[a-z0-9]$/.test(project) ||
    !/^https:\/\/portfolio-api-[0-9]{1,20}\.[a-z]+(?:-[a-z0-9]+)+[0-9]\.run\.app$/.test(origin) ||
    env.FOLIOVIEW_PORTFOLIO_AUDIENCE !== origin
  )
    return null;
  return { project, origin, audience: origin };
}

function ruleFor(
  request: Request,
  edgeOrigin: ReturnType<typeof createEdgeOriginVerifier>,
): { path: string; rule: Rule } {
  // Inspect the original string too: URL parsers normalize literal and escaped dot segments.
  const url = new URL(request.url);
  if (url.search || request.url.includes("?")) fail("unsupported_query");
  if (/[\\%#]/.test(request.url)) fail();
  requireSameOrigin(request, url, edgeOrigin);
  if (!url.pathname.startsWith(PREFIX + "/")) fail();
  const path = url.pathname.slice(PREFIX.length);
  if (
    request.method === "POST" &&
    new RegExp(`^/api/v3/holdings/sources/${ID}/view/query$`).test(path)
  ) {
    if (
      request.headers.has("x-folioview-delegation") ||
      request.headers.has("x-serverless-authorization")
    )
      fail("insufficient_scope");
    return { path, rule: { kind: "view", max: 16384 } };
  }
  if (
    (request.method === "GET" &&
      new RegExp(`^${SOURCE}/operation-cancellations/${OPERATION}$`).test(path)) ||
    (request.method === "POST" && new RegExp(`^${SOURCE}/operation-cancellations$`).test(path))
  ) {
    if (
      request.headers.has("x-folioview-delegation") ||
      request.headers.has("x-serverless-authorization")
    )
      fail("insufficient_scope");
    const read = request.method === "GET";
    return {
      path,
      rule: {
        kind: read ? "read" : "cancellation",
        max: read ? 0 : 8192,
        cancel: { slot: path.split("/")[5], ...(read ? { id: path.split("/").at(-1)! } : {}) },
      },
    };
  }
  if (
    request.method === "GET" &&
    new RegExp(
      `^${SOURCE}(?:/latest|/snapshots/${ID}|/(?:operations|mutations)/${OPERATION})?$`,
    ).test(path)
  )
    return { path, rule: { kind: "read", max: 0 } };
  if (request.method === "PUT" && new RegExp(`^${SOURCE}/snapshots/${ID}$`).test(path))
    return { path, rule: { kind: "snapshot", max: 589824 } };
  if (
    request.method === "POST" &&
    new RegExp(`^${SOURCE}/mutations/(?:fence|disconnect|delete)$`).test(path)
  )
    return { path, rule: { kind: "mutation", max: 66560 } };
  if (
    request.method === "POST" &&
    new RegExp(`^${SOURCE}/mutations/${OPERATION}/synchronize$`).test(path)
  )
    return { path, rule: { kind: "synchronize", max: 1024 } };
  if (request.method === "POST" && new RegExp(`^${SOURCE}/authority-sync$`).test(path))
    return { path, rule: { kind: "authority", max: 1024 } };
  if (
    request.method === "POST" &&
    new RegExp(`^${SOURCE}/operations/${OPERATION}/synchronize-revision$`).test(path)
  )
    return { path, rule: { kind: "revision", max: 1024 } };
  return fail();
}

async function transport(request: Request, rule: Rule, signal: AbortSignal) {
  if (request.headers.get("x-folioview-contract") !== CONTRACT) fail("unsupported_contract");
  const auth = request.headers.get("authorization") ?? "";
  if (auth.length > 8192 || !auth.startsWith("Bearer ") || !JWT.test(auth.slice(7)))
    fail("invalid_token");
  const headers = new Headers({ Authorization: auth, "X-FolioView-Contract": CONTRACT });
  for (const name of [
    "idempotency-key",
    "x-folioview-author-key",
    "x-folioview-authority-delegation",
  ]) {
    const value = request.headers.get(name);
    const allowed =
      rule.kind === "cancellation"
        ? name === "idempotency-key"
        : rule.kind === "authority"
          ? name === "x-folioview-authority-delegation"
          : rule.kind !== "read" &&
            rule.kind !== "view" &&
            rule.kind !== "synchronize" &&
            rule.kind !== "revision" &&
            name !== "x-folioview-authority-delegation";
    if (allowed) {
      if (
        !value ||
        !(name === "idempotency-key"
          ? /^[A-Za-z0-9_-]{22,128}$/.test(value)
          : name === "x-folioview-author-key"
            ? /^[A-Za-z0-9_-]{43}$/.test(value)
            : value.length <= 16384 && JWT.test(value))
      )
        fail();
      headers.set(name, value!);
    } else if (value !== null) fail();
  }
  if (request.headers.has("content-encoding")) fail("unsupported_media_type");
  const raw = await bytes(request.body, rule.max, signal);
  if (rule.kind === "read")
    return { headers, raw: undefined, token: auth.slice(7), viewExpected: undefined };
  if (request.headers.get("content-type")?.split(";", 1)[0].toLowerCase() !== "application/json")
    fail("unsupported_media_type");
  const body = json(raw);
  let viewExpected: HoldingsViewExpected | undefined;
  if (rule.kind === "view") {
    if (holdingsViewRequest(body, new URL(request.url).pathname.slice(PREFIX.length).split("/")[5]))
      viewExpected = body.expected;
    else return fail();
  } else if (rule.kind === "cancellation") {
    if (!cancellationRequest("holdings", body, rule.cancel!.slot, headers.get("idempotency-key")!))
      fail();
  } else if (
    rule.kind === "authority" &&
    fields(body, ["contractVersion", "vaultId", "nonce", "minimumRegistryEpoch"])
  ) {
    if (
      body.contractVersion !== CONTRACT ||
      typeof body.vaultId !== "string" ||
      !new RegExp(`^${ID}$`).test(body.vaultId) ||
      typeof body.nonce !== "string" ||
      !new RegExp(`^${OPERATION}$`).test(body.nonce) ||
      !integer(body.minimumRegistryEpoch, 2)
    )
      fail();
  } else if (rule.kind === "authority" || rule.kind === "synchronize" || rule.kind === "revision") {
    if (!fields(body, ["contractVersion"]) || body.contractVersion !== CONTRACT) fail();
  } else if (rule.kind === "snapshot") {
    if (
      !fields(body, ["contractVersion", "expectedRevision", "carrier"]) ||
      body.contractVersion !== CONTRACT ||
      !integer(body.expectedRevision, 0) ||
      !carrier(body.carrier)
    )
      fail();
  } else if (
    !fields(body, ["contractVersion", "expectedVersion", "expectedSourceEpoch", "command"]) ||
    body.contractVersion !== CONTRACT ||
    !integer(body.expectedVersion, 1) ||
    !integer(body.expectedSourceEpoch, 1) ||
    !signedObject(body.command)
  )
    fail();
  headers.set("Content-Type", "application/json");
  return {
    headers,
    raw,
    token: auth.slice(7),
    viewExpected,
  };
}

function synchronizedReceipt(value: unknown, path: string) {
  if (
    !fields(value, [
      "contractVersion",
      "operationId",
      "action",
      "resourceRef",
      "sourceEpoch",
      "state",
      "requestedAt",
      "completedAt",
    ]) ||
    value.contractVersion !== CONTRACT ||
    value.state !== "acknowledged" ||
    typeof value.operationId !== "string" ||
    value.operationId !== path.split("/")[7] ||
    !["fence", "disconnect", "delete"].includes(value.action as string) ||
    !integer(value.sourceEpoch, 1) ||
    !fields(value.resourceRef, ["kind", "sourceService", "resourceId", "incarnation"]) ||
    value.resourceRef.kind !== "holdings" ||
    value.resourceRef.sourceService !== "portfolio" ||
    value.resourceRef.resourceId !== path.split("/")[5] ||
    typeof value.resourceRef.incarnation !== "string" ||
    !new RegExp(`^${ID}$`).test(value.resourceRef.incarnation)
  )
    return false;
  const time = (v: unknown) =>
    typeof v === "string" &&
    /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$/.test(v) &&
    Number.isFinite(Date.parse(v)) &&
    new Date(v).toISOString().slice(0, 19) === v.slice(0, 19);
  return (
    time(value.requestedAt) &&
    time(value.completedAt) &&
    Date.parse(value.completedAt as string) >= Date.parse(value.requestedAt as string)
  );
}

function confirmedRevision(value: unknown, path: string) {
  const parts = path.split("/");
  return (
    fields(value, [
      "contractVersion",
      "vaultId",
      "resourceRef",
      "snapshotId",
      "revision",
      "sourceEpoch",
      "stableOperationId",
      "envelopeFingerprint",
    ]) &&
    value.contractVersion === CONTRACT &&
    value.stableOperationId === parts[7] &&
    integer(value.revision, 1) &&
    integer(value.sourceEpoch, 1) &&
    [value.vaultId, value.snapshotId].every(
      (id) => typeof id === "string" && new RegExp(`^${ID}$`).test(id),
    ) &&
    fields(value.resourceRef, ["kind", "sourceService", "resourceId", "incarnation"]) &&
    value.resourceRef.resourceId === parts[5] &&
    value.resourceRef.kind === "holdings" &&
    value.resourceRef.sourceService === "portfolio" &&
    typeof value.resourceRef.incarnation === "string" &&
    new RegExp(`^${ID}$`).test(value.resourceRef.incarnation) &&
    typeof value.envelopeFingerprint === "string" &&
    /^[a-f0-9]{64}$/.test(value.envelopeFingerprint)
  );
}

export function createPortfolioProxy(options: Options = {}) {
  const env = options.env ?? process.env;
  const send = options.fetch ?? fetch;
  const now = options.now ?? Date.now;
  const edgeOrigin = createEdgeOriginVerifier(env, now);
  const verifyOwner = createFirebaseVerifier(send, now);
  const identity = createCloudRunIdentity(send, now);

  return async function portfolioProxy(request: Request): Promise<Response> {
    const started = proxyClock();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), options.deadlineMs ?? 12000);
    const signal = AbortSignal.any([request.signal, controller.signal]);
    try {
      const config = portfolioConfiguration(env);
      if (!config) fail("authorization_unavailable");
      const { path, rule } = ruleFor(request, edgeOrigin);
      const { headers, raw, token, viewExpected } = await transport(request, rule, signal);
      const uid = await verifyOwner(token, config!.project, signal);
      headers.set(
        "X-Serverless-Authorization",
        `Bearer ${await until(identity(config!.audience), signal)}`,
      );
      const response = await until(
        send(config!.origin + path, {
          method: request.method,
          headers,
          body: raw,
          signal,
          redirect: "manual",
          cache: "no-store",
          credentials: "omit",
        }),
        signal,
      );
      if (
        (rule.kind === "view" ||
          rule.kind === "synchronize" ||
          rule.kind === "revision" ||
          rule.cancel) &&
        response.status < 400 &&
        response.status !== 200
      )
        fail("authorization_unavailable");
      return timeProxyResponse(
        await forwardResponse(
          response,
          signal,
          rule.kind === "view"
            ? (value) => {
                try {
                  if (!viewExpected) return false;
                  parseHoldingsView(value, viewExpected);
                  return true;
                } catch {
                  return false;
                }
              }
            : rule.cancel
              ? (value) =>
                  cancellationResponse(
                    "holdings",
                    value,
                    rule.cancel!.slot,
                    rule.cancel!.id ?? headers.get("idempotency-key") ?? undefined,
                  )
              : rule.kind === "synchronize"
                ? (value) => synchronizedReceipt(value, path)
                : rule.kind === "revision"
                  ? (value) => confirmedRevision(value, path)
                  : undefined,
        ),
        started,
      );
    } catch (error) {
      return timeProxyResponse(
        errorResponse(error instanceof Failure ? error.code : "authorization_unavailable"),
        started,
      );
    } finally {
      clearTimeout(timer);
    }
  };
}

export const portfolioProxy = createPortfolioProxy();
