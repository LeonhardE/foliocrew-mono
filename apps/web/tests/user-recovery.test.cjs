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
const ORIGINAL_HEAD = VAULT + "/original-registry-head/read";
const CHECK = VAULT + "/handover/check";
const HANDOVER = VAULT + "/handover";
const START = VAULT + "/registry-start/read";
const ADVANCE = VAULT + "/registry/advance";
const REGISTER = VAULT + "/holdings-sources/holdings_A";
const CURRENT = routes.OWNER_CURRENT_PATH;
const ALIASES = VAULT + "/display-names/read";
const RENEWAL = VAULT + "/key-renewals/apply";
const RENEWAL_RECEIPT = VAULT + "/key-renewals/read";
const PATHS = [
  EVIDENCE,
  PAGE,
  ORIGINAL_HEAD,
  START,
  ADVANCE,
  REGISTER,
  CURRENT,
  ALIASES,
  RENEWAL,
  RENEWAL_RECEIPT,
];
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
const START_BODY = { ...SCOPE, profile: routes.REGISTRY_START_PROFILE, nonce: "n".repeat(32) };
const ADVANCE_BODY = {
  ...SCOPE,
  profile: routes.REGISTRY_UPDATE_PROFILE,
  operationId: "synthetic_registry_update_A",
  expectedVaultVersion: 2,
  registryBundle: BUNDLE,
};
const REGISTER_BODY = {
  ...SCOPE,
  profile: routes.HOLDINGS_REGISTRATION_PROFILE,
  operationId: "synthetic_holdings_registration_A",
  sourceId: "holdings_A",
  command: PROOF,
};
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
    {
      "server-only": {},
      "./owner-transport": transport,
      "../display-name-contract": compile(
        "../lib/display-name-contract.ts",
        {
          "./task-types": compile("../lib/task-types.ts"),
        },
        globals,
      ),
      canonicalize: (await import("canonicalize")).default,
    },
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
  const compatibility = {
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
      ...(compatibility[input.profile] ? { ...scope, ...compatibility[input.profile] } : result),
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

test("User writes bind the original registry receipt and the generated holdings incarnation", async () => {
  const headers = { "X-FolioView-Contract": CONTRACT };
  const canonical = (value) =>
    JSON.stringify(value, (_key, item) =>
      item && typeof item === "object" && !Array.isArray(item)
        ? Object.fromEntries(
            Object.keys(item)
              .sort()
              .map((key) => [key, item[key]]),
          )
        : item,
    );
  const registry = {
    ...SCOPE,
    profile: routes.REGISTRY_UPDATE_PROFILE,
    operationId: ADVANCE_BODY.operationId,
    requestDigest: digest(canonical(ADVANCE_BODY)),
    vaultVersion: 3,
    registry: NEXT_HEAD,
  };
  const source = {
    contractVersion: CONTRACT,
    source: {
      sourceEpoch: 1,
      resourceRef: {
        kind: "holdings",
        sourceService: "portfolio",
        resourceId: "holdings_A",
        incarnation: "inc_" + digest(PROOF.protected + "." + PROOF.payload).slice(0, 32),
      },
    },
  };
  const { proxy } = fixture({
    reply: (input) =>
      Response.json(input.profile === registry.profile ? registry : source, { headers }),
  });
  assert.equal((await proxy(request(ADVANCE, ADVANCE_BODY))).status, 200);
  assert.equal((await proxy(request(REGISTER, REGISTER_BODY))).status, 200);
  assert.equal(
    (await proxy(request(REGISTER, { ...REGISTER_BODY, sourceId: "holdings_B" }))).status,
    400,
  );
  assert.equal(
    (await proxy(request(ADVANCE, { ...ADVANCE_BODY, expectedVaultVersion: 3 }))).status,
    503,
  );
  const other = fixture({
    reply: () =>
      Response.json(
        {
          ...source,
          source: {
            ...source.source,
            resourceRef: { ...source.source.resourceRef, incarnation: "inc_other" },
          },
        },
        { headers },
      ),
  });
  assert.equal((await other.proxy(request(REGISTER, REGISTER_BODY))).status, 503);
});

test("the alias proxy respects the selected Owner and rejects foreign ciphertext", async () => {
  const payload = {
    ...SCOPE,
    profile: routes.PRIVATE_DISPLAY_NAME_PROFILE,
    sourceId: null,
    operationId: null,
  };
  const body = { contractVersion: CONTRACT, profile: payload.profile, items: [] };
  const reply = (value) => Response.json(value, { headers: { "X-FolioView-Contract": CONTRACT } });
  const normal = fixture({
    env: { ...ENV, FOLIOVIEW_USER_CURRENT_OWNER: OWNER },
    reply: () => reply(body),
  });
  assert.equal((await normal.proxy(request(ALIASES, payload))).status, 200);
  assert.equal(
    (await normal.proxy(request(ALIASES, { ...payload, operationId: "synthetic_alias_original" })))
      .status,
    400,
  );
  const denied = fixture({ reply: () => reply(body) });
  assert.equal((await denied.proxy(request(ALIASES, payload))).status, 404);
  const wrong = fixture({
    env: { ...ENV, FOLIOVIEW_USER_CURRENT_OWNER: OWNER },
    reply: () =>
      reply({
        ...body,
        items: [
          {
            state: {
              contractVersion: CONTRACT,
              profile: payload.profile,
              ownerSubject: "b".repeat(64),
              vaultId: "vault_A",
              rootKeyId: "r".repeat(43),
              recipientKeyId: "k".repeat(43),
              ref: {
                kind: "holdings",
                sourceService: "portfolio",
                resourceId: "holdings_A",
                incarnation: "instance_A",
              },
              revision: 1,
              stableOperationId: "synthetic_alias_original",
              operationFingerprint: "d".repeat(64),
              acceptedAt: 1000,
            },
            command: PROOF,
          },
        ],
      }),
  });
  assert.equal((await wrong.proxy(request(ALIASES, payload))).status, 503);
});

test("the selected User renewal matches both signed controls and the receipt operation", async () => {
  const rootKeyId = "r".repeat(43);
  const scope = {
    ...SCOPE,
    profile: routes.USER_KEY_RENEWAL_PROFILE,
    operationId: "synthetic_owner_key_renewal",
    nonce: "x".repeat(32),
  };
  const archiveCommand = { ...PROOF, payload: "eQY" };
  const packet = {
    ...scope,
    registryBundle: BUNDLE,
    command: PROOF,
    archiveCommand,
    archive: {
      profile: "folioview.passkey-vault.v1",
      ownerSubject: OWNER,
      vaultId: scope.vaultId,
      rootKeyId,
      credentialId: "ZQ",
      prfSalt: "p".repeat(43),
      iv: "i".repeat(16),
      ciphertext: "y".repeat(30),
    },
  };
  const result = {
    ...scope,
    result: {
      contractVersion: CONTRACT,
      profile: "folioview.vault-key-renewal.v1",
      receipt: {
        profile: "folioview.vault-key-renewal.v1",
        ownerSubject: OWNER,
        vaultId: scope.vaultId,
        operationId: scope.operationId,
        rootKeyId,
        commandFingerprint: digest(PROOF.protected + "." + PROOF.payload),
        archiveCommandFingerprint: digest(archiveCommand.protected + "." + archiveCommand.payload),
      },
    },
  };
  const env = { ...ENV, FOLIOVIEW_USER_CURRENT_OWNER: OWNER };
  const reply = (value) => Response.json(value, { headers: { "X-FolioView-Contract": CONTRACT } });
  const normal = fixture({ env, reply: () => reply(result) });
  const written = await normal.proxy(request(RENEWAL, packet));
  assert.equal(written.status, 200);
  assert.equal(written.headers.get("cache-control"), "no-store");
  assert.deepEqual(await written.json(), result);
  assert.equal((await normal.proxy(request(RENEWAL_RECEIPT, scope))).status, 200);
  assert.equal(
    (await normal.proxy(request(RENEWAL, { ...packet, archiveCommand: PROOF }))).status,
    503,
  );
  assert.equal(
    (
      await normal.proxy(
        request(RENEWAL, {
          ...packet,
          archive: { ...packet.archive, ownerSubject: "f".repeat(64) },
        }),
      )
    ).status,
    400,
  );
  const wrong = fixture({ env, reply: () => reply({ ...result, nonce: "y".repeat(32) }) });
  assert.equal((await wrong.proxy(request(RENEWAL_RECEIPT, scope))).status, 503);
});

test("selected Owner startup binds the User reply to the fresh nonce and fails closed", async () => {
  const header = { "X-FolioView-Contract": CONTRACT };
  const input = {
    contractVersion: CONTRACT,
    profile: routes.OWNER_CURRENT_PROFILE,
    ownerSubject: OWNER,
    nonce: "n".repeat(32),
  };
  const rootKeyId = "r".repeat(43);
  const value = {
    ...input,
    vault: {
      vaultId: "vault_A",
      rootKeyId,
      rootJwk: { kty: "EC", crv: "P-256", x: "x".repeat(43), y: "y".repeat(43) },
      version: 2,
      archive: {
        profile: "folioview.passkey-vault.v1",
        ownerSubject: OWNER,
        vaultId: "vault_A",
        rootKeyId,
        credentialId: "synthetic_credential",
        prfSalt: "p".repeat(43),
        iv: "i".repeat(16),
        ciphertext: "synthetic_sealed_ciphertext",
      },
      registryHistory: [BUNDLE],
    },
    proof: {
      registry: NEXT_HEAD,
      registryStart: NEXT_HEAD,
      signedTransition: PROOF,
      archive: { state: "active", version: 1, digest: "a".repeat(64) },
      sourcesDigest: "b".repeat(64),
      sources: [],
    },
  };
  const env = { ...ENV, FOLIOVIEW_USER_CURRENT_OWNER: OWNER };
  const ok = fixture({ env, reply: () => Response.json(value, { headers: header }) });
  assert.equal((await ok.proxy(request(CURRENT, input))).status, 200);
  const stale = fixture({
    env,
    reply: () => Response.json({ ...value, nonce: "old" }, { headers: header }),
  });
  assert.equal((await stale.proxy(request(CURRENT, input))).status, 503);
  const absent = fixture({
    env,
    reply: () =>
      Response.json(
        { contractVersion: CONTRACT, error: { code: "not_found" } },
        { status: 404, headers: header },
      ),
  });
  assert.equal((await absent.proxy(request(CURRENT, input))).status, 503);
  const other = fixture({ env: { ...env, FOLIOVIEW_USER_CURRENT_OWNER: "f".repeat(64) } });
  assert.equal((await other.proxy(request(CURRENT, input))).status, 404);
  assert.equal(other.calls.length, 1);
});

test("registry-start evidence retains fixed scope and nonce validation", async () => {
  const { proxy, calls } = fixture();
  const result = await proxy(request(START, START_BODY));
  assert.equal(result.status, 200);
  assert.equal(result.headers.get("Cache-Control"), "no-store");
  assert.equal(result.headers.get("Set-Cookie"), null);
  assert.deepEqual(
    calls.map(([url]) => url).filter((url) => new URL(url).origin === ORIGIN),
    [ORIGIN + START],
  );
  const wrongNonce = fixture({ reply: (input) => response(input, { nonce: "q".repeat(32) }) });
  assert.equal((await wrongNonce.proxy(request(START, START_BODY))).status, 503);

  const foreign = fixture();
  assert.equal(
    (await foreign.proxy(request(START, { ...START_BODY, ownerSubject: "0".repeat(64) }))).status,
    404,
  );
  assert.deepEqual(
    foreign.calls.map(([url]) => url),
    [JWKS],
  );
});

test("the original registry head is bound to the selected owner and exact legacy target", async () => {
  const body = { ...SCOPE, profile: routes.ORIGINAL_REGISTRY_HEAD_PROFILE, target: HEAD };
  const reply = (input) =>
    Response.json(
      { ...input, rootKeyId: "r".repeat(43), bundle: BUNDLE },
      { headers: { "X-FolioView-Contract": CONTRACT } },
    );
  const env = { ...ENV, FOLIOVIEW_USER_CURRENT_OWNER: OWNER };
  const accepted = fixture({ env, reply });
  const result = await accepted.proxy(request(ORIGINAL_HEAD, body));
  assert.equal(result.status, 200);
  assert.equal(result.headers.get("Cache-Control"), "no-store");
  const wrong = fixture({ env, reply: (input) => reply({ ...input, target: NEXT_HEAD }) });
  assert.equal((await wrong.proxy(request(ORIGINAL_HEAD, body))).status, 503);
  const foreign = fixture({ env: { ...env, FOLIOVIEW_USER_CURRENT_OWNER: "0".repeat(64) }, reply });
  assert.equal((await foreign.proxy(request(ORIGINAL_HEAD, body))).status, 404);
  assert.deepEqual(
    foreign.calls.map(([url]) => url),
    [JWKS],
  );
  const older = fixture({ env, reply: () => Response.json({}, { status: 404 }) });
  assert.deepEqual(
    await (await older.proxy(request(ORIGINAL_HEAD, body))).json().then((doc) => doc.error.code),
    "not_found",
  );
});

test("retired handover paths are not forwarded, including with an old deployment flag", async () => {
  const { proxy, calls } = fixture({ env: { ...ENV, FOLIOVIEW_USER_HANDOVER_OWNER: OWNER } });
  for (const path of [CHECK, HANDOVER]) {
    assert.equal(routes.userRecoveryRoute(path), null);
    assert.equal((await proxy(request(path, SCOPE))).status, 400);
  }
  assert.equal(calls.length, 0);
});
