const assert = require("node:assert/strict");
const test = require("node:test");
const { compile } = require("./resource-library-helpers.cjs");

const { WORKSPACE_INVITATIONS: PATH } = compile("../lib/workspace-invitations.ts");
const SITE = "https://workspace.example.test";
const ORIGIN = "https://user-api-123456789.northamerica-northeast2.run.app";
const TARGET = ORIGIN + "/api/v1/workspace-invitations";
const JWKS =
  "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com";
const PROJECT = "fictional-project";
const NOW = Date.now();
const EMAIL = "fictional.member@gmail.com";
const INVITATION = {
  id: "a".repeat(64),
  revision: "b".repeat(32),
  email: EMAIL,
  status: "invited",
  updatedAt: 1800000000,
  expiresAt: 1800010000,
  canRetry: false,
  canRevoke: true,
};
let createProxy;
let token;
let jwk;

test.before(async () => {
  const jose = await import("jose");
  const { privateKey, publicKey } = await jose.generateKeyPair("RS256");
  jwk = { ...(await jose.exportJWK(publicKey)), kid: "fixture", alg: "RS256", use: "sig" };
  token = await new jose.SignJWT({
    iss: `https://securetoken.google.com/${PROJECT}`,
    aud: PROJECT,
    sub: "synthetic-admin",
    exp: Math.floor(NOW / 1000) + 600,
    iat: Math.floor(NOW / 1000) - 1,
    auth_time: Math.floor(NOW / 1000) - 1,
    firebase: { sign_in_provider: "google.com" },
  })
    .setProtectedHeader({ alg: "RS256", kid: jwk.kid })
    .sign(privateKey);
  const globals = { fetch, URL, Buffer, AbortSignal, process: { env: {} } };
  const transport = compile(
    "../lib/server/owner-transport.ts",
    { "server-only": {}, jose },
    globals,
  );
  createProxy = compile(
    "../lib/server/workspace-invitations.ts",
    { "server-only": {}, "./owner-transport": transport },
    globals,
  ).createWorkspaceInvitationsProxy;
});

function setup(reply, env = {}) {
  const forwarded = [];
  const handle = createProxy({
    env: {
      FOLIOCREW_INVITATION_UI_ENABLED: "1",
      FOLIOVIEW_USER_ORIGIN: ORIGIN,
      FOLIOVIEW_OWNER_FIREBASE_PROJECT_ID: PROJECT,
      ...env,
    },
    now: () => NOW,
    fetch: async (url, options) => {
      if (url === JWKS) return Response.json({ keys: [jwk] });
      forwarded.push({ url, options });
      return reply();
    },
  });
  return { handle, forwarded };
}

function request(path = "", { method = "GET", headers = {}, body } = {}) {
  return new Request(SITE + PATH + path, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    body,
  });
}

test("only the selected User origin receives the verified browser token and invitation body", async () => {
  const { handle, forwarded } = setup(() => Response.json(INVITATION));
  const body = JSON.stringify({ email: EMAIL });
  const response = await handle(
    request("", {
      method: "POST",
      headers: { Origin: SITE, "X-User-Id": "forged", Cookie: "discard=me" },
      body,
    }),
  );
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.deepEqual(await response.json(), INVITATION);
  assert.equal(forwarded.length, 1);
  assert.equal(forwarded[0].url, TARGET);
  assert.equal(forwarded[0].options.body.toString(), body);
  assert.equal(forwarded[0].options.headers.Authorization, `Bearer ${token}`);
  assert.equal(Object.keys(forwarded[0].options.headers).length, 2);
  assert.equal(forwarded[0].options.redirect, "error");
});

test("invalid methods, paths, payloads and origins never reach the User API", async () => {
  const { handle, forwarded } = setup(() => Response.json(INVITATION));
  const invalid = [
    [request("/capability", { method: "POST" }), 404],
    [request("?after=" + "c".repeat(64) + "&next=1"), 404],
    [request("", { method: "POST", body: '{"email":"not-gmail@example.test"}' }), 422],
    [request("", { method: "POST", body: JSON.stringify({ email: EMAIL, admin: true }) }), 422],
    [request("", { headers: { Origin: "https://other.example.test" } }), 403],
    [request("", { headers: { Authorization: "Bearer invalid" } }), 401],
  ];
  for (const [input, expected] of invalid) assert.equal((await handle(input)).status, expected);
  assert.equal(forwarded.length, 0);
});

test("capability and forbidden responses omit backend fields and remain uncached", async () => {
  const denied = setup(() => Response.json({ detail: "private backend detail" }, { status: 403 }));
  const response = await denied.handle(request());
  assert.equal(response.status, 403);
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.doesNotMatch(await response.text(), /private backend detail/);
  const capability = setup(() => Response.json({ canManageInvitations: false }));
  assert.deepEqual(await (await capability.handle(request("/capability"))).json(), {
    canManageInvitations: false,
  });
  const leak = setup(() => Response.json({ canManageInvitations: true, adminUid: "secret" }));
  assert.equal((await leak.handle(request("/capability"))).status, 503);
  const disabled = setup(() => assert.fail("disabled proxy forwarded a request"), {
    FOLIOCREW_INVITATION_UI_ENABLED: "",
  });
  assert.equal((await disabled.handle(request("/capability"))).status, 404);
});

test("list cursors and delivery revisions are scoped to the fixed routes", async () => {
  const cursor = "c".repeat(64);
  const list = setup(() => Response.json({ items: [INVITATION], nextCursor: cursor }));
  assert.equal((await list.handle(request(`?after=${cursor}`))).status, 200);
  assert.equal(list.forwarded[0].url, TARGET + `?after=${cursor}`);
  const retry = setup(() => Response.json(INVITATION));
  const suffix = `/${INVITATION.id}/${INVITATION.revision}/retry`;
  assert.equal((await retry.handle(request(suffix, { method: "POST" }))).status, 200);
  assert.equal(retry.forwarded[0].url, TARGET + suffix);
  assert.equal(retry.forwarded[0].options.body, undefined);
});
