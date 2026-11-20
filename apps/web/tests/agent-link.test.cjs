const assert = require("node:assert/strict");
const test = require("node:test");
const { compile, contracts } = require("./agent-connections-helpers.cjs");

const legacy = "https://agent-hub-api-123456789.northamerica-northeast2.run.app";
const brand = contracts.BRANDED_AGENT_ORIGIN;
const { agentLinkConfiguration } = compile("../lib/server/agent-link.ts", {
  "server-only": {},
  "../agent-connections": contracts,
  "./hub-owner": { hubConfiguration: (env) => (env.HUB_DISABLED ? null : { origin: legacy }) },
});
const { readAgentLinkConfiguration } = compile("../lib/agent-link.ts", {
  "./agent-connections": contracts,
});
const plain = (object) => JSON.parse(JSON.stringify(object));

test("Agent link keeps the original response and safely stages the branded copy default", () => {
  const first = agentLinkConfiguration({ FOLIOVIEW_AGENT_BRAND_ORIGIN: brand });
  assert.deepEqual(plain(readAgentLinkConfiguration(first)), {
    schemaVersion: 1,
    enabled: true,
    hubOrigin: legacy,
  });
  const disabled = { HUB_DISABLED: "1", FOLIOVIEW_AGENT_BRAND_ORIGIN: brand };
  assert.deepEqual(plain(readAgentLinkConfiguration(agentLinkConfiguration(disabled, 2))), {
    schemaVersion: 2,
    enabled: false,
    hubOrigin: null,
    brandOrigin: null,
    preferredOrigin: null,
  });
  const env = { FOLIOVIEW_AGENT_BRAND_ORIGIN: brand };
  const staged = agentLinkConfiguration(env, 2);
  assert.deepEqual(plain(readAgentLinkConfiguration(staged)), {
    schemaVersion: 2,
    enabled: true,
    hubOrigin: legacy,
    brandOrigin: brand,
    preferredOrigin: legacy,
  });
  assert.equal(
    readAgentLinkConfiguration(
      agentLinkConfiguration({ ...env, FOLIOVIEW_AGENT_PREFER_BRAND: "1" }, 2),
    ).preferredOrigin,
    brand,
  );
  const unknown = "https://mcp.foliocrew.app.example";
  assert.equal(
    agentLinkConfiguration({ FOLIOVIEW_AGENT_BRAND_ORIGIN: unknown }, 2).brandOrigin,
    null,
  );
  for (const patch of [
    { brandOrigin: unknown },
    { preferredOrigin: unknown },
    { brandOrigin: null, preferredOrigin: brand },
    { hubOrigin: brand },
  ])
    assert.throws(
      () => readAgentLinkConfiguration({ ...staged, ...patch }),
      (error) => error.code === "invalid_response",
    );
});
