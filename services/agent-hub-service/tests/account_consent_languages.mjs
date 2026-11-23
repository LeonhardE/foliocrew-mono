import assert from "node:assert/strict";

for (const [preferences, fallback, language, heading, action, unavailable] of [
  [
    ["en-CA"],
    "en-CA",
    "en",
    /Connect your Agent to Foliocrew/,
    /Continue to Foliocrew/,
    /Try again/,
  ],
  [
    ["fr", "zh-CN"],
    "fr",
    "zh-CN",
    /连接 Agent 与 Foliocrew/,
    /继续到 Foliocrew/,
    /请从 Agent 重试/,
  ],
  [
    ["zh-Hans-TW"],
    "zh-Hans-TW",
    "zh-CN",
    /连接 Agent 与 Foliocrew/,
    /继续到 Foliocrew/,
    /请从 Agent 重试/,
  ],
  [
    ["zh-Hant"],
    "zh-Hant",
    "zh-Hant",
    /連線 Agent 與 Foliocrew/,
    /繼續前往 Foliocrew/,
    /請從 Agent 重試/,
  ],
  [[], "zh-HK", "zh-Hant", /連線 Agent 與 Foliocrew/, /繼續前往 Foliocrew/, /請從 Agent 重試/],
]) {
  const nodes = new Map(["#status", "#continue", "#return-to-agent", "h1"].map((id) => [id, {}]));
  globalThis.document = { querySelector: (id) => nodes.get(id), documentElement: {} };
  Object.defineProperty(globalThis, "navigator", {
    value: { languages: preferences, language: fallback },
    configurable: true,
  });
  // An invalid request tests the localized failure before any network call.
  globalThis.location = { search: "" };
  globalThis.fetch = () => assert.fail("an invalid request must not query the network");
  const page = new URL("../account-link/dist/account-consent-page.mjs", import.meta.url);
  page.searchParams.set("case", preferences.join(",") || fallback);
  await import(page.href);
  assert.equal(document.documentElement.lang, language);
  assert.match(document.title, heading);
  assert.equal(document.title, nodes.get("h1").textContent);
  assert.match(nodes.get("#continue").textContent, action);
  assert.match(nodes.get("#status").textContent, unavailable);
}
