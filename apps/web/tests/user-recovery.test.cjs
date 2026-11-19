const assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const test = require("node:test");
const { compile } = require("./resource-library-helpers.cjs");

const NOW = Date.parse("2026-11-19T08:30:00Z");
const CONTRACT = "folioview.agent-workspace.v2.0";
const SITE = "https://folioview.example.test";
const ORIGIN = "https://user-api-123456789.northamerica-northeast2.run.app";
const JWKS =
  "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com";
const METADATA =
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity";
const ENV = {
  FOLIOVIEW_USER_OWNER_ENABLED: "true",
  FOLIOVIEW_USER_ORIGIN: ORIGIN,
  FOLIOVIEW_OWNER_FIREBASE_PROJECT_ID: "fixture-project",
};
const routes = compile("../lib/user-recovery-route.ts");
const VAULT = "/api/v3/private-resources/vaults/vault_A";
const EVIDENCE = VAULT + "/recovery-evidence";
const PAGE = VAULT + "/registry-pages/read";
const CHECK = VAULT + "/handover/check";
const HANDOVER = VAULT + "/handover";
const START = VAULT + "/registry-start/read";
const PATHS = [EVIDENCE, PAGE, CHECK, HANDOVER, START];
const digest = (value) => createHash("sha256").update(value).digest("hex");
const OWNER = digest("owner_A");
const HEAD = {
  registryEpoch: 1,
  registrySequence: 2,
  keyEpoch: 1,
  checkpointDigest: "a".repeat(64),
};
const PAYLOAD = {
  contractVersion: CONTRACT,
  profile: routes.RECOVERY_PROFILE,
  ownerSubject: OWNER,
  vaultId: "vault_A",
  nonce: "n".repeat(32),
  deviceId: "device_A",
  deviceSigningKeyId: "s".repeat(43),
  deviceEncryptionKeyId: "e".repeat(43),
};
const PROOF = { protected: "eA", payload: "eQ", signature: "eg" };
const BUNDLE = {
  contractVersion: CONTRACT,
  checkpoint: PROOF,
  entries: [{ certificate: PROOF, active: true }],
};
const NEXT_HEAD = { ...HEAD, registryEpoch: 2, registrySequence: 3 };
const SCOPE = { contractVersion: CONTRACT, ownerSubject: OWNER, vaultId: "vault_A" };
const CHECK_BODY = { ...SCOPE, profile: routes.HANDOVER_CHECK_PROFILE };
const HANDOVER_BODY = {
  ...SCOPE,
  profile: routes.HANDOVER_PROFILE,
  operationId: "synthetic_transition_requested",
  signedTransition: PROOF,
  firstBundle: BUNDLE,
};
const START_BODY = { ...SCOPE, profile: routes.REGISTRY_START_PROFILE, nonce: "n".repeat(32) };
const PAGE_PAYLOAD = {
  contractVersion: CONTRACT,
  profile: routes.REGISTRY_PAGE_PROFILE,
  ownerSubject: OWNER,
  vaultId: "vault_A",
  base: null,
  target: HEAD,
};
let token;
let workload;
let jwk;
let createProxy;

test.before(async () => {
  const jose = await import("jose");
  const { privateKey, publicKey } = await jose.generateKeyPair("RS256");
  jwk = { ...(await jose.exportJWK(publicKey)), kid: "fixture", alg: "RS256", use: "sig" };
  const sign = (claims) =>
    new jose.SignJWT(claims).setProtectedHeader({ alg: "RS256", kid: jwk.kid }).sign(privateKey);
  token = await sign({
    iss: "https://securetoken.google.com/fixture-project",
    aud: "fixture-project",
    sub: "owner_A",
    exp: NOW / 1000 + 600,
    iat: NOW / 1000 - 1,
    auth_time: NOW / 1000 - 1,
    firebase: { sign_in_provider: "google.com" },
  });
  workload = await sign({
    iss: "https://accounts.google.com",
    aud: ORIGIN,
    exp: NOW / 1000 + 600,
  });
  const globals = {
    fetch,
    Headers,
    Request,
    URL,
    Buffer,
    AbortSignal,
    setTimeout,
    clearTimeout,
    process: { env: {} },
  };
  const transport = compile(
    "../lib/server/owner-transport.ts",
    { "server-only": {}, jose },
    globals,
  );
  createProxy = compile(
    "../lib/server/user-recovery.ts",
    { "server-only": {}, "./owner-transport": transport },
    globals,
  ).createUserRecoveryProxy;
});

function request(path = EVIDENCE, body = PAYLOAD, headers = {}) {
  return new Request(SITE + routes.USER_RECOVERY_PROXY + path, {
    method: "POST",
    body: JSON.stringify(body),
    headers: {
      Origin: SITE,
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "X-FolioView-Contract": CONTRACT,
      ...headers,
    },
  });
}

function response(input, patch = {}) {
  const scope = {
    contractVersion: CONTRACT,
    profile: input.profile,
    ownerSubject: input.ownerSubject,
    vaultId: input.vaultId,
    rootKeyId: "r".repeat(43),
  };
  const handovers = {
    [routes.HANDOVER_CHECK_PROFILE]: { status: "ready", vaultVersion: 1 },
    [routes.HANDOVER_PROFILE]: {
      operationId: input.operationId,
      baselineDigest: "a".repeat(64),
      transitionFingerprint: digest(PROOF.protected + "." + PROOF.payload),
      nextVaultVersion: 2,
      registryStart: NEXT_HEAD,
      writerEpoch: 2,
    },
    [routes.REGISTRY_START_PROFILE]: {
      nonce: input.nonce,
      vaultVersion: 2,
      archive: { state: "active", version: 1, digest: "b".repeat(64) },
      registry: NEXT_HEAD,
      registryStart: NEXT_HEAD,
      sourcesDigest: "c".repeat(64),
      rootJwk: { kty: "EC", crv: "P-256", x: "x".repeat(43), y: "y".repeat(43) },
      signedTransition: PROOF,
      firstBundle: BUNDLE,
    },
  };
  const signed = PROOF;
  const result =
    input.profile === routes.RECOVERY_PROFILE
      ? {
          ...scope,
          requestDigest: digest(JSON.stringify(input, Object.keys(input).sort())),
          vaultVersion: 1,
          registry: HEAD,
          archive: { state: "active", version: 1, digest: "a".repeat(64) },
          device: "active",
          sourcesDigest: "a".repeat(64),
          verifiedAt: NOW / 1000,
          expiresAt: NOW / 1000 + 60,
          registryStart: null,
        }
      : {
          ...scope,
          base: input.base,
          target: input.target,
          bundles: [
            {
              contractVersion: CONTRACT,
              checkpoint: signed,
              entries: [{ certificate: signed, active: true }],
            },
          ],
        };
  return Response.json(
    {
      ...(handovers[input.profile] ? { ...scope, ...handovers[input.profile] } : result),
      ...patch,
    },
    { headers: { "X-FolioView-Contract": CONTRACT, "Set-Cookie": "fixture=private" } },
  );
}

function fixture({ env = ENV, reply = response } = {}) {
  const calls = [];
  const proxy = createProxy({
    env,
    now: () => NOW,
    fetch: async (url, options) => {
      calls.push([url, options]);
      if (url === JWKS) return Response.json({ keys: [jwk] });
      if (url === METADATA + `?audience=${encodeURIComponent(ORIGIN)}&format=full`)
        return new Response(workload, { headers: { "Metadata-Flavor": "Google" } });
      assert.ok(PATHS.some((path) => ORIGIN + path === url));
      return reply(JSON.parse(new TextDecoder().decode(options.body)));
    },
  });
  return { proxy, calls };
}

test("both recovery reads send separate Owner and workload credentials to the fixed origin", async () => {
  const { proxy, calls } = fixture();
  for (const input of [request(), request(PAGE, PAGE_PAYLOAD)]) {
    const result = await proxy(input);
    assert.equal(result.status, 200);
    assert.equal(result.headers.get("Cache-Control"), "no-store");
    assert.equal(result.headers.get("Set-Cookie"), null);
  }
  assert.equal(calls.filter(([url]) => url.startsWith(METADATA)).length, 1);
  const forwarded = calls.filter(([url]) => [ORIGIN + EVIDENCE, ORIGIN + PAGE].includes(url));
  assert.deepEqual(
    forwarded.map(([url]) => url),
    [ORIGIN + EVIDENCE, ORIGIN + PAGE],
  );
  for (const [, sent] of forwarded) {
    assert.equal(sent.headers.Authorization, `Bearer ${token}`);
    assert.equal(sent.headers["X-FolioView-Proxy-Authorization"], `Bearer ${workload}`);
    assert.equal(sent.redirect, "manual");
    assert.equal(sent.cache, "no-store");
  }
});

test("the proxy declines unknown paths, cross-origin input, forged headers and another owner", async () => {
  for (const [input, expected, callCount] of [
    [request(EVIDENCE + "?override=1"), 400, 0],
    [request(VAULT + "/mutate"), 400, 0],
    [request(EVIDENCE, PAYLOAD, { Origin: "https://outside.invalid" }), 403, 0],
    [request(EVIDENCE, PAYLOAD, { "X-FolioView-Proxy-Authorization": "forged" }), 403, 0],
    [request(EVIDENCE, PAYLOAD, { Authorization: "Bearer invalid" }), 401, 0],
    [request(EVIDENCE, { ...PAYLOAD, vaultId: "vault_B" }), 400, 0],
    [request(EVIDENCE, { ...PAYLOAD, ownerSubject: "f".repeat(64) }), 404, 1],
  ]) {
    const { proxy, calls } = fixture();
    assert.equal((await proxy(input)).status, expected);
    assert.equal(calls.length, callCount);
  }

  const disabled = fixture({ env: {} });
  assert.equal((await disabled.proxy(request())).status, 503);
  assert.equal(disabled.calls.length, 0);
});

test("unbound recovery evidence and registry page data stay behind the proxy", async () => {
  const wrongNonce = fixture({
    reply: (input) => response(input, { requestDigest: "f".repeat(64) }),
  });
  assert.equal((await wrongNonce.proxy(request())).status, 503);
  const wrongEpoch = fixture({
    reply: (input) => response(input, { target: { ...HEAD, registryEpoch: 2 } }),
  });
  assert.equal((await wrongEpoch.proxy(request(PAGE, PAGE_PAYLOAD))).status, 503);
  const extra = fixture({ reply: (input) => response(input, { legacy: "unexpected" }) });
  assert.equal((await extra.proxy(request())).status, 503);
});

test("the three handover requests use fixed scope and signed-input receipt identity", async () => {
  const { proxy, calls } = fixture();
  for (const [path, value] of [
    [CHECK, CHECK_BODY],
    [HANDOVER, HANDOVER_BODY],
    [START, START_BODY],
  ]) {
    const result = await proxy(request(path, value));
    assert.equal(result.status, 200);
    assert.equal(result.headers.get("Cache-Control"), "no-store");
    assert.equal(result.headers.get("Set-Cookie"), null);
  }
  assert.deepEqual(
    calls.map(([url]) => url).filter((url) => new URL(url).origin === ORIGIN),
    [ORIGIN + CHECK, ORIGIN + HANDOVER, ORIGIN + START],
  );
  const wrongReceipt = fixture({
    reply: (input) => response(input, { transitionFingerprint: "0".repeat(64) }),
  });
  assert.equal((await wrongReceipt.proxy(request(HANDOVER, HANDOVER_BODY))).status, 503);
  const wrongNonce = fixture({ reply: (input) => response(input, { nonce: "q".repeat(32) }) });
  assert.equal((await wrongNonce.proxy(request(START, START_BODY))).status, 503);
});

test("handover rejects foreign scope and any plaintext Passkey material before forwarding", async () => {
  const foreign = fixture();
  assert.equal(
    (await foreign.proxy(request(CHECK, { ...CHECK_BODY, ownerSubject: "0".repeat(64) }))).status,
    404,
  );
  assert.deepEqual(
    foreign.calls.map(([url]) => url),
    [JWKS],
  );
  const plaintext = fixture();
  assert.equal(
    (await plaintext.proxy(request(HANDOVER, { ...HANDOVER_BODY, prf: "forbidden" }))).status,
    400,
  );
  assert.equal(plaintext.calls.length, 0);
});
