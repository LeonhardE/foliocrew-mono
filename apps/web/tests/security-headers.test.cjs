const assert = require("node:assert/strict"),
  test = require("node:test"),
  path = require("node:path"),
  vm = require("node:vm");
const { compile } = require("./resource-library-helpers.cjs");
const config = compile(
  "../next.config.ts",
  {
    "node:path": path,
    "node:crypto": require("node:crypto"),
    "node:fs": require("node:fs"),
  },
  { __dirname: path.resolve(__dirname, "..") },
).default;
async function routeHeaders(route) {
  const result = new Map();
  for (const rule of await config.headers()) {
    if (rule.source !== "/:path*" && rule.source !== route) continue;
    for (const { key, value } of rule.headers) result.set(key.toLowerCase(), value);
  }
  return result;
}
function policy(headers) {
  return new Map(
    headers
      .get("content-security-policy")
      .split(";")
      .map((v) => v.trim().split(/\s+/))
      .filter((v) => v[0])
      .map(([key, ...values]) => [key, values]),
  );
}
test("actual Next header configuration restricts framing objects and base URLs on every route while preserving Agent referrers", async () => {
  for (const route of [
    "/",
    "/agents",
    "/tasks",
    "/resources",
    "/settings",
    "/api/private/agent-hub/api/v2/vaults/current",
    "/_next/static/chunks/example.js",
  ]) {
    const headers = await routeHeaders(route),
      csp = policy(headers);
    assert.deepEqual(Object.fromEntries(csp), {
      "frame-ancestors": ["'none'"],
      "object-src": ["'none'"],
      "base-uri": ["'self'"],
    });
    assert.equal(headers.get("x-frame-options"), "DENY");
    assert.equal(headers.get("x-content-type-options"), "nosniff");
    assert.equal(
      headers.get("referrer-policy"),
      route === "/agents" ? "no-referrer" : "strict-origin-when-cross-origin",
    );
  }
});
test("minimal policy leaves original Firebase popup Worker and inline theme execution available without claiming full script CSP", async () => {
  const headers = await routeHeaders("/tasks"),
    csp = policy(headers);
  for (const key of [
    "default-src",
    "script-src",
    "script-src-elem",
    "connect-src",
    "worker-src",
    "child-src",
    "frame-src",
    "sandbox",
  ])
    assert.equal(csp.has(key), false);
  assert.equal(headers.has("cross-origin-opener-policy"), false); // Original Google/native popup opener remains usable.
  assert.equal(headers.has("permissions-policy"), false); // No new Passkey permission restriction.
  const { THEME_BOOTSTRAP_SCRIPT } = compile("../lib/theme-bootstrap.ts");
  const root = { dataset: {}, style: {} };
  vm.runInNewContext(THEME_BOOTSTRAP_SCRIPT, {
    localStorage: { getItem: () => "dark" },
    matchMedia: () => ({ matches: false }),
    document: { documentElement: root },
  });
  assert.equal(root.dataset.theme, "dark");
  assert.equal(root.style.colorScheme, "dark");
});
