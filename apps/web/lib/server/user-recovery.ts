import "server-only";

import canonicalize from "canonicalize";
import { createHash } from "node:crypto";
import { displayNameResponse } from "../display-name-contract";
import {
  HANDOVER_CHECK_PROFILE,
  HANDOVER_PROFILE,
  HOLDINGS_REGISTRATION_PROFILE,
  OWNER_CURRENT_PROFILE,
  PRIVATE_DISPLAY_NAME_PROFILE,
  RECOVERY_PROFILE,
  REGISTRY_START_PROFILE,
  REGISTRY_UPDATE_PROFILE,
  USER_ARCHIVE_LIFECYCLE_PROFILE,
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
const OPAQUE = /^[A-Za-z0-9_-]+$/;
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
    (rule.vault !== null && value.vaultId !== rule.vault) ||
    !matches(value.ownerSubject, DIGEST)
  )
    return false;

  if (rule.profile === HANDOVER_CHECK_PROFILE) return true;
  if (rule.profile === HANDOVER_PROFILE)
    return (
      matches(value.operationId, NONCE) &&
      signedObject(value.signedTransition) &&
      registryBundle(value.firstBundle)
    );
  if (rule.profile === REGISTRY_START_PROFILE) return matches(value.nonce, NONCE);
  if (rule.profile === OWNER_CURRENT_PROFILE) return matches(value.nonce, NONCE);
  if (rule.profile === USER_ARCHIVE_LIFECYCLE_PROFILE)
    return (
      matches(value.nonce, NONCE) &&
      (value.operationId === null || matches(value.operationId, NONCE))
    );
  if (rule.profile === REGISTRY_UPDATE_PROFILE)
    return (
      matches(value.operationId, NONCE) &&
      integer(value.expectedVaultVersion, 1) &&
      registryBundle(value.registryBundle)
    );
  if (rule.profile === PRIVATE_DISPLAY_NAME_PROFILE) {
    if (rule.keys.includes("command"))
      return (
        matches(value.sourceId, ID) &&
        matches(value.operationId, NONCE) &&
        signedObject(value.command)
      );
    return value.sourceId === null
      ? value.operationId === null
      : matches(value.sourceId, ID) &&
          (value.operationId === null || matches(value.operationId, NONCE));
  }
  if (rule.profile === HOLDINGS_REGISTRATION_PROFILE)
    return (
      value.sourceId === rule.source &&
      matches(value.operationId, NONCE) &&
      signedObject(value.command)
    );
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
    activeArchive(value.archive) &&
    value.device === "active" &&
    matches(value.sourcesDigest, DIGEST) &&
    integer(value.verifiedAt, 0) &&
    integer(value.expiresAt, 1) &&
    Number(value.verifiedAt) < Number(value.expiresAt) &&
    Number(value.expiresAt) - Number(value.verifiedAt) <= 60
  );
}

function activeArchive(value: unknown) {
  return (
    fields(value, ["state", "version", "digest"]) &&
    value.state === "active" &&
    integer(value.version, 1) &&
    matches(value.digest, DIGEST)
  );
}

function registryBundle(bundle: unknown) {
  return (
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
    )
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
    value.bundles.every(registryBundle)
  );
}

const SCOPE_FIELDS = ["contractVersion", "profile", "ownerSubject", "vaultId", "rootKeyId"];

function validHandoverCheck(value: Json) {
  if (value.status === "ready") {
    return (
      fields(value, [...SCOPE_FIELDS, "status", "vaultVersion"]) && integer(value.vaultVersion, 1)
    );
  }
  return (
    fields(value, [...SCOPE_FIELDS, "status", "operationId"]) &&
    value.status === "installed" &&
    matches(value.operationId, NONCE)
  );
}

function validHandoverReceipt(value: Json, input: Json) {
  const signed = input.signedTransition;
  return (
    record(signed) &&
    value.transitionFingerprint === digest(signed.protected + "." + signed.payload) &&
    fields(value, [
      ...SCOPE_FIELDS,
      "operationId",
      "baselineDigest",
      "transitionFingerprint",
      "nextVaultVersion",
      "registryStart",
      "writerEpoch",
    ]) &&
    value.operationId === input.operationId &&
    matches(value.baselineDigest, DIGEST) &&
    matches(value.transitionFingerprint, DIGEST) &&
    integer(value.nextVaultVersion, 2) &&
    head(value.registryStart) &&
    value.registryStart.registryEpoch === 2 &&
    value.writerEpoch === 2
  );
}

function validRegistryStart(value: Json, input: Json) {
  return (
    fields(value, [
      ...SCOPE_FIELDS,
      "nonce",
      "vaultVersion",
      "archive",
      "registry",
      "registryStart",
      "sourcesDigest",
      "rootJwk",
      "signedTransition",
      "firstBundle",
    ]) &&
    value.nonce === input.nonce &&
    integer(value.vaultVersion, 2) &&
    activeArchive(value.archive) &&
    head(value.registry) &&
    head(value.registryStart) &&
    value.registryStart.registryEpoch === 2 &&
    value.registry.registryEpoch === value.registryStart.registryEpoch &&
    Number(value.registry.registrySequence) >= Number(value.registryStart.registrySequence) &&
    matches(value.sourcesDigest, DIGEST) &&
    fields(value.rootJwk, ["kty", "crv", "x", "y"]) &&
    value.rootJwk.kty === "EC" &&
    value.rootJwk.crv === "P-256" &&
    matches(value.rootJwk.x, KEY) &&
    matches(value.rootJwk.y, KEY) &&
    signedObject(value.signedTransition) &&
    registryBundle(value.firstBundle)
  );
}

function validReply(body: unknown, input: Json, expectedDigest: string) {
  if (input.profile === OWNER_CURRENT_PROFILE) {
    if (
      !fields(body, ["contractVersion", "profile", "ownerSubject", "nonce", "vault", "proof"]) ||
      body.contractVersion !== CONTRACT ||
      body.profile !== input.profile ||
      body.ownerSubject !== input.ownerSubject ||
      body.nonce !== input.nonce ||
      !fields(body.vault, [
        "vaultId",
        "rootKeyId",
        "rootJwk",
        "version",
        "archive",
        "registryHistory",
      ]) ||
      !matches(body.vault.vaultId, ID) ||
      !matches(body.vault.rootKeyId, KEY) ||
      !fields(body.vault.rootJwk, ["kty", "crv", "x", "y"]) ||
      body.vault.rootJwk.kty !== "EC" ||
      body.vault.rootJwk.crv !== "P-256" ||
      !matches(body.vault.rootJwk.x, KEY) ||
      !matches(body.vault.rootJwk.y, KEY) ||
      !integer(body.vault.version, 2) ||
      !Array.isArray(body.vault.registryHistory) ||
      body.vault.registryHistory.length < 1 ||
      body.vault.registryHistory.length > 129 ||
      !body.vault.registryHistory.every(registryBundle) ||
      !fields(body.vault.archive, [
        "profile",
        "ownerSubject",
        "vaultId",
        "rootKeyId",
        "credentialId",
        "prfSalt",
        "iv",
        "ciphertext",
      ]) ||
      body.vault.archive.profile !== "folioview.passkey-vault.v1" ||
      body.vault.archive.ownerSubject !== input.ownerSubject ||
      body.vault.archive.vaultId !== body.vault.vaultId ||
      body.vault.archive.rootKeyId !== body.vault.rootKeyId ||
      !matches(body.vault.archive.credentialId, OPAQUE) ||
      String(body.vault.archive.credentialId).length > 2048 ||
      !matches(body.vault.archive.prfSalt, KEY) ||
      !matches(body.vault.archive.iv, /^[A-Za-z0-9_-]{16}$/) ||
      !matches(body.vault.archive.ciphertext, OPAQUE) ||
      String(body.vault.archive.ciphertext).length > 450_000 ||
      !fields(body.proof, [
        "registry",
        "registryStart",
        "signedTransition",
        "archive",
        "sourcesDigest",
        "sources",
      ])
    )
      return false;
    return (
      head(body.proof.registry) &&
      head(body.proof.registryStart) &&
      body.proof.registryStart.registryEpoch === 2 &&
      body.proof.registry.registryEpoch === 2 &&
      activeArchive(body.proof.archive) &&
      signedObject(body.proof.signedTransition) &&
      matches(body.proof.sourcesDigest, DIGEST) &&
      Array.isArray(body.proof.sources) &&
      body.proof.sources.length <= 12
    );
  }
  if (input.profile === HOLDINGS_REGISTRATION_PROFILE) {
    return (
      record(input.command) &&
      fields(body, ["contractVersion", "source"]) &&
      body.contractVersion === CONTRACT &&
      fields(body.source, ["resourceRef", "sourceEpoch"]) &&
      body.source.sourceEpoch === 1 &&
      fields(body.source.resourceRef, ["kind", "sourceService", "resourceId", "incarnation"]) &&
      body.source.resourceRef.kind === "holdings" &&
      body.source.resourceRef.sourceService === "portfolio" &&
      body.source.resourceRef.resourceId === input.sourceId &&
      body.source.resourceRef.incarnation ===
        "inc_" + digest(input.command.protected + "." + input.command.payload).slice(0, 32)
    );
  }
  if (input.profile === REGISTRY_UPDATE_PROFILE) {
    return (
      fields(body, [
        "contractVersion",
        "profile",
        "ownerSubject",
        "vaultId",
        "operationId",
        "requestDigest",
        "vaultVersion",
        "registry",
      ]) &&
      body.contractVersion === CONTRACT &&
      body.profile === input.profile &&
      body.ownerSubject === input.ownerSubject &&
      body.vaultId === input.vaultId &&
      body.operationId === input.operationId &&
      body.requestDigest === expectedDigest &&
      integer(body.vaultVersion, 2) &&
      body.vaultVersion === Number(input.expectedVaultVersion) + 1 &&
      head(body.registry) &&
      Number(body.registry.registryEpoch) >= 2
    );
  }
  if (input.profile === PRIVATE_DISPLAY_NAME_PROFILE) {
    const path = `/api/v3/private-display-names/${input.vaultId}/holdings${input.sourceId ? "/" + input.sourceId : ""}`;
    const operation = typeof input.operationId === "string" ? input.operationId : undefined;
    if (!displayNameResponse(path, body, operation) || !record(body)) return false;
    const items = input.sourceId === null ? body.items : body.item ? [body.item] : [];
    return (
      Array.isArray(items) &&
      items.every(
        (item) =>
          record(item) && record(item.state) && item.state.ownerSubject === input.ownerSubject,
      )
    );
  }
  if (input.profile === USER_ARCHIVE_LIFECYCLE_PROFILE) {
    const scope = ["contractVersion", "profile", "ownerSubject", "vaultId", "rootKeyId", "nonce"];
    if (!fieldsBelongToRequest(body, input) || body.nonce !== input.nonce) return false;
    if (input.operationId !== null)
      return (
        fields(body, [...scope, "operationId", "receipt"]) &&
        body.operationId === input.operationId &&
        record(body.receipt) &&
        body.receipt.operationId === input.operationId &&
        body.receipt.ownerSubject === input.ownerSubject &&
        body.receipt.vaultId === input.vaultId &&
        body.receipt.rootKeyId === body.rootKeyId
      );
    return (
      fields(body, [...scope, "state", "originalCheckpoints"]) &&
      record(body.state) &&
      body.state.contractVersion === CONTRACT &&
      body.state.profile === "folioview.vault-lifecycle.v1" &&
      body.state.vaultId === input.vaultId &&
      body.state.rootKeyId === body.rootKeyId &&
      Array.isArray(body.state.history) &&
      body.state.history.length <= 32 &&
      Array.isArray(body.originalCheckpoints) &&
      body.originalCheckpoints.length <= 32 &&
      body.originalCheckpoints.every(signedObject)
    );
  }
  if (!fieldsBelongToRequest(body, input)) return false;
  switch (input.profile) {
    case RECOVERY_PROFILE:
      return validEvidence(body, expectedDigest);
    case HANDOVER_CHECK_PROFILE:
      return validHandoverCheck(body);
    case HANDOVER_PROFILE:
      return validHandoverReceipt(body, input);
    case REGISTRY_START_PROFILE:
      return validRegistryStart(body, input);
    default:
      return validPage(body, input);
  }
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
      const raw = await bytes(request.body, rule.maxRequestBytes, signal);
      const input = json(raw);
      if (!validRequest(input, rule)) return fail();
      const uid = await verifyOwner(authorization.slice(7), project, signal);
      if (input.ownerSubject !== digest(uid)) fail("not_found");
      if (
        rule.profile === OWNER_CURRENT_PROFILE ||
        rule.profile === PRIVATE_DISPLAY_NAME_PROFILE ||
        rule.profile === USER_ARCHIVE_LIFECYCLE_PROFILE
      ) {
        const selected = env.FOLIOVIEW_USER_CURRENT_OWNER;
        if (!selected) fail("not_found");
        if (!matches(selected, DIGEST)) fail("authorization_unavailable");
        if (selected !== input.ownerSubject) fail("not_found");
      }
      if (rule.profile === HANDOVER_CHECK_PROFILE || rule.profile === HANDOVER_PROFILE) {
        const selected = env.FOLIOVIEW_USER_HANDOVER_OWNER;
        if (selected !== undefined && !matches(selected, DIGEST)) fail("authorization_unavailable");
        if (selected !== undefined && selected !== input.ownerSubject) fail("not_found");
      }

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
      if (rule.profile === OWNER_CURRENT_PROFILE && response.status === 404)
        fail("authorization_unavailable");
      // These closed evidence fields are ASCII strings. Sorting the top-level
      // keys gives the exact UTF-8 canonical input hashed by User.
      const expectedDigest =
        rule.profile === RECOVERY_PROFILE
          ? digest(JSON.stringify(input, [...rule.keys].sort()))
          : rule.profile === REGISTRY_UPDATE_PROFILE
            ? digest(canonicalize(input) ?? fail())
            : "";
      const result = await forwardResponse(response, signal, (body) =>
        validReply(body, input, expectedDigest),
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

function fieldsBelongToRequest(body: unknown, input: Json): body is Json {
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
