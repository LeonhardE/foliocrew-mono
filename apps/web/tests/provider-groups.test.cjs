const test = require("node:test"),
  assert = require("node:assert/strict");
const { compile } = require("./resource-library-helpers.cjs"),
  { providerGroups } = compile("../lib/provider-groups.ts");
function row(id, expires = 2000) {
  return {
    connection: { provider: "muse", connectionId: id, status: "active" },
    credential: {
      status: "active",
      expiresAt: expires,
      reference: {
        connectionId: id,
        clientId: "client",
        credentialGeneration: 1,
        credentialFingerprint: id.repeat(64).slice(0, 64),
      },
    },
    tasks: [],
  };
}
test("one live Muse credential is current while expired records stay in history", () => {
  const old = row("a", 900),
    next = row("b");
  const g = providerGroups([old, next], {}, 1000)[0];
  assert.equal(g.current, next);
  assert.equal(g.history[0], old);
  assert.equal(g.reviewRequired, false);
});
test("multiple live legacy credentials require review, never choosing an arbitrary winner", () => {
  const g = providerGroups([row("a"), row("b")], {}, 1000)[0];
  assert.equal(g.current, null);
  assert.equal(g.reviewRequired, true);
  assert.equal(g.history.length, 2);
});
test("the exact canonical slot wins and stale references never fall back to a different credential", () => {
  const a = row("a"),
    b = row("b"),
    state = { muse: { slot: { currentCredential: a.credential.reference }, legacyBlockers: [] } };
  let g = providerGroups([b, a], state, 1000)[0];
  assert.equal(g.current, a);
  state.muse.slot.currentCredential = { ...a.credential.reference, credentialGeneration: 2 };
  g = providerGroups([a, b], state, 1000)[0];
  assert.equal(g.current, null);
  assert.equal(g.reviewRequired, true);
  state.muse.slot.currentCredential = null;
  g = providerGroups([a, b], state, 1000)[0];
  assert.equal(g.current, null);
});

test("management history counts only previous accounts that can still be unlinked", () => {
  for (const provider of ["muse", "chatgpt"]) {
    const current = row("a"),
      expired = row("b", 900),
      former = row("c");
    const views = [former, current, expired];
    for (const view of views) view.connection.provider = provider;
    former.connection.status = "revoked";
    const states = { [provider]: { slot: { currentCredential: current.credential.reference } } };
    const group = () =>
      providerGroups(views, states, 1000).find((item) => item.provider === provider);
    assert.equal(group().current, current);
    assert.deepEqual(
      group().history.map((entry) => entry.connection.connectionId),
      [expired.connection.connectionId],
    );
    expired.connection.status = "revoked";
    assert.equal(group().history.length, 0);
    assert.equal(views.length, 3);
  }
});

test("revoked accounts leave both providers unconnected even with a retired slot and blockers", () => {
  const muse = row("m"),
    chatgpt = row("c");
  muse.connection.status = "revoked";
  chatgpt.connection.provider = "chatgpt";
  chatgpt.connection.status = "revoked";
  const reference = chatgpt.credential.reference;
  chatgpt.credential = null;
  const states = {
    chatgpt: { slot: { currentCredential: reference }, legacyBlockers: ["c"] },
  };
  const groups = () => providerGroups([muse, chatgpt], states, 1000);
  for (const group of groups()) {
    assert.equal(group.current, null);
    assert.equal(group.history.length, 0);
    assert.equal(group.reviewRequired, false);
  }
  states.chatgpt.legacyBlockers.push("unknown");
  assert.equal(groups()[1].reviewRequired, true);
});
