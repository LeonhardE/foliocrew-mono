import "server-only";

import { createHash } from "node:crypto";
import {
  RECOVERY_PROFILE,
  USER_RECOVERY_MAX_REQUEST,
  USER_RECOVERY_PROXY,
  userRecoveryRoute,
} from "../user-recovery-route";
import {
  CONTRACT,
  JWT,
  Failure,
  bytes,
  createCloudRunIdentity,
  createEdgeOriginVerifier,
  createFirebaseVerifier,
  errorResponse,
  fail,
  fields,
  forwardResponse,
  integer,
  json,
  proxyClock,
  record,
  requireSameOrigin,
  signedObject,
  timeProxyResponse,
  until,
  type Json,
  type Options,
} from "./owner-transport";

const KEY = /^[A-Za-z0-9_-]{43}$/;
const ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;
const NONCE = /^[A-Za-z0-9_-]{22,128}$/;
const DIGEST = /^[a-f0-9]{64}$/;
const HEAD_FIELDS = ["registryEpoch", "registrySequence", "checkpointDigest", "keyEpoch"];
const UNSUPPORTED_HEADERS = [
  "idempotency-key",
  "x-folioview-author-key",
  "x-folioview-authority-delegation",
  "x-folioview-delegation",
  "x-folioview-proxy-authorization",
  "x-serverless-authorization",
];

function matches(value: unknown, pattern: RegExp) {
  return typeof value === "string" && pattern.test(value) && !/[\r\n]/.test(value);
}

function head(value: unknown): value is Json {
  return (
    fields(value, HEAD_FIELDS) &&
    integer(value.registryEpoch, 1) &&
    integer(value.registrySequence, 1) &&
    integer(value.keyEpoch, 1) &&
    matches(value.checkpointDigest, DIGEST)
  );
}

function sameHead(value: unknown, expected: unknown) {
  return expected === null
    ? value === null
    : head(value) && head(expected) && HEAD_FIELDS.every((key) => value[key] === expected[key]);
}

function digest(value: string) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function validRequest(
  value: unknown,
  rule: NonNullable<ReturnType<typeof userRecoveryRoute>>,
): value is Json {
  if (
    !fields(value, rule.keys) ||
    value.contractVersion !== CONTRACT ||
    value.profile !== rule.profile ||
    value.vaultId !== rule.vault ||
    !matches(value.ownerSubject, DIGEST)
  )
    return false;

  if (rule.profile === RECOVERY_PROFILE)
    return (
      matches(value.nonce, NONCE) &&
      matches(value.deviceId, ID) &&
      matches(value.deviceSigningKeyId, KEY) &&
      matches(value.deviceEncryptionKeyId, KEY)
    );
  return head(value.target) && (value.base === null || head(value.base));
}

function validEvidence(value: unknown, expectedDigest: string) {
  return (
    fields(value, [
      "contractVersion",
      "profile",
      "ownerSubject",
      "vaultId",
      "rootKeyId",
      "requestDigest",
      "vaultVersion",
      "registry",
      "archive",
      "device",
      "sourcesDigest",
      "verifiedAt",
      "expiresAt",
      "registryStart",
    ]) &&
    value.requestDigest === expectedDigest &&
    integer(value.vaultVersion, 1) &&
    head(value.registry) &&
    (value.registryStart === null || head(value.registryStart)) &&
    fields(value.archive, ["state", "version", "digest"]) &&
    value.archive.state === "active" &&
    integer(value.archive.version, 1) &&
    matches(value.archive.digest, DIGEST) &&
    value.device === "active" &&
    matches(value.sourcesDigest, DIGEST) &&
    integer(value.verifiedAt, 0) &&
    integer(value.expiresAt, 1) &&
    Number(value.verifiedAt) < Number(value.expiresAt) &&
    Number(value.expiresAt) - Number(value.verifiedAt) <= 60
  );
}

function validPage(value: unknown, input: Json) {
  return (
    fields(value, [
      "contractVersion",
      "profile",
      "ownerSubject",
      "vaultId",
      "rootKeyId",
      "base",
      "target",
      "bundles",
    ]) &&
    sameHead(value.base, input.base) &&
    sameHead(value.target, input.target) &&
    Array.isArray(value.bundles) &&
    value.bundles.length > 0 &&
    value.bundles.length <= 4 &&
    value.bundles.every(
      (bundle) =>
        fields(bundle, ["contractVersion", "checkpoint", "entries"]) &&
        bundle.contractVersion === CONTRACT &&
        signedObject(bundle.checkpoint) &&
        Array.isArray(bundle.entries) &&
        bundle.entries.length > 0 &&
        bundle.entries.length <= 64 &&
        bundle.entries.every(
          (entry) =>
            fields(entry, ["certificate", "active"]) &&
            typeof entry.active === "boolean" &&
            signedObject(entry.certificate),
        ),
    )
  );
}

export function createUserRecoveryProxy(options: Options = {}) {
  const env = options.env ?? process.env;
  const send = options.fetch ?? fetch;
  const now = options.now ?? Date.now;
  const edgeOrigin = createEdgeOriginVerifier(env, now);
  const verifyOwner = createFirebaseVerifier(send, now);
  const identity = createCloudRunIdentity(send, now);

  return async function userRecoveryProxy(request: Request) {
    const started = proxyClock();
    const signal = AbortSignal.any([
      request.signal,
      AbortSignal.timeout(options.deadlineMs ?? 12000),
    ]);
    try {
      const origin = env.FOLIOVIEW_USER_ORIGIN ?? "";
      const project = env.FOLIOVIEW_OWNER_FIREBASE_PROJECT_ID ?? "";
      if (
        env.FOLIOVIEW_USER_OWNER_ENABLED !== "true" ||
        !/^https:\/\/user-api-[0-9]{1,20}\.[a-z]+(?:-[a-z0-9]+)+[0-9]\.run\.app$/.test(origin) ||
        new URL(origin).origin !== origin ||
        !/^[a-z][a-z0-9-]{4,28}[a-z0-9]$/.test(project)
      )
        fail("authorization_unavailable");
      const url = new URL(request.url);
      if (request.url.includes("?")) fail("unsupported_query");
      if (/[\\%#]/.test(request.url)) fail();
      requireSameOrigin(request, url, edgeOrigin);
      const path = url.pathname.slice(USER_RECOVERY_PROXY.length);
      const rule = url.pathname.startsWith(USER_RECOVERY_PROXY + "/")
        ? userRecoveryRoute(path)
        : null;
      if (!rule || request.method !== "POST") return fail();
      if (UNSUPPORTED_HEADERS.some((name) => request.headers.has(name))) fail("insufficient_scope");
      if (request.headers.get("x-folioview-contract") !== CONTRACT) fail("unsupported_contract");
      const authorization = request.headers.get("authorization") ?? "";
      if (
        authorization.length > 8192 ||
        !/^Bearer /.test(authorization) ||
        !JWT.test(authorization.slice(7))
      )
        fail("invalid_token");
      if (
        request.headers.get("content-type")?.split(";", 1)[0].toLowerCase() !== "application/json"
      )
        fail("unsupported_media_type");
      const raw = await bytes(request.body, USER_RECOVERY_MAX_REQUEST, signal);
      const input = json(raw);
      if (!validRequest(input, rule)) return fail();
      const uid = await verifyOwner(authorization.slice(7), project, signal);
      if (input.ownerSubject !== digest(uid)) fail("not_found");

      const token = await until(identity(origin), signal);
      const response = await until(
        send(origin + path, {
          method: "POST",
          headers: {
            Authorization: authorization,
            "Content-Type": "application/json",
            "X-FolioView-Contract": CONTRACT,
            "X-FolioView-Proxy-Authorization": `Bearer ${token}`,
          },
          body: raw,
          signal,
          redirect: "manual",
          cache: "no-store",
          credentials: "omit",
        }),
        signal,
      );
      if (
        response.status < 400 &&
        (response.status !== 200 || response.headers.get("x-folioview-contract") !== CONTRACT)
      )
        fail("authorization_unavailable");
      // These closed evidence fields are ASCII strings. Sorting the top-level
      // keys gives the exact UTF-8 canonical input hashed by User.
      const expectedDigest =
        rule.profile === RECOVERY_PROFILE
          ? digest(JSON.stringify(input, [...rule.keys].sort()))
          : "";
      const result = await forwardResponse(
        response,
        signal,
        (body) =>
          fieldsBelongToRequest(body, input) &&
          (rule.profile === RECOVERY_PROFILE
            ? validEvidence(body, expectedDigest)
            : validPage(body, input)),
      );
      return timeProxyResponse(result, started);
    } catch (error) {
      return timeProxyResponse(
        errorResponse(error instanceof Failure ? error.code : "authorization_unavailable"),
        started,
      );
    }
  };
}

function fieldsBelongToRequest(body: unknown, input: Json) {
  return (
    record(body) &&
    body.contractVersion === CONTRACT &&
    body.profile === input.profile &&
    body.ownerSubject === input.ownerSubject &&
    body.vaultId === input.vaultId &&
    matches(body.rootKeyId, KEY)
  );
}

export const userRecoveryProxy = createUserRecoveryProxy();
