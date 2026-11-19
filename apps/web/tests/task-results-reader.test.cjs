const test = require("node:test"),
  assert = require("node:assert/strict");
const { compile } = require("./resource-library-helpers.cjs");
const reader = compile("../lib/task-result-reader.ts"),
  { DisplayLru } = compile("../lib/workspace-cache.ts");
const C = reader.RESULT_CONTRACT,
  content = {
    title: "PRIVATE_REPORT",
    summary: "PRIVATE_SUMMARY",
    sections: [{ sectionId: "summary", markdown: "PRIVATE_BODY" }],
    limitations: [],
  };
const pm = () => ({
  resultId: "presult_A",
  taskId: "task_A",
  runId: "run_A",
  connectionId: "connection_A",
  receivedAt: 1000,
  stateVersion: 0,
  read: false,
  starred: false,
  archived: false,
});
test("persistent preloading is read-only; opening revalidates visibility and reuses the immutable body after a read flag changes", async () => {
  let calls = 0,
    decrypts = 0,
    read = false;
  const raw = {
    metadata: pm(),
    envelope: { synthetic: "CIPHERTEXT" },
    manifest: { runId: "run_A" },
    identity: {},
    binding: {},
    receipt: {},
  };
  const w = {
    vault: { vaultId: "vault_A" },
    openPersistentResult: async (args) => {
      decrypts++;
      assert.equal(args.resultId, "presult_A");
      return content;
    },
  };
  const cache = new DisplayLru(10, 16000000),
    row = { kind: "persistent", metadata: pm(), triggerKind: "legacy_unknown" },
    api = async (path) => {
      calls++;
      assert.equal(path, "/api/v2/persistent-results/vault_A/presult_A");
      return { ...raw, metadata: { ...raw.metadata, read, stateVersion: read ? 1 : 0 } };
    };
  const args = { row, workspace: w, api, cache, scope: "owner:vault:1", assert() {} };
  assert.equal(
    (await reader.readTaskResult({ ...args, fresh: false })).content.title,
    "PRIVATE_REPORT",
  );
  assert.equal(calls, 1);
  assert.equal(decrypts, 1);
  await reader.readTaskResult({ ...args, fresh: false });
  assert.equal(calls, 1);
  read = true;
  const opened = await reader.readTaskResult(args);
  assert.equal(calls, 2);
  assert.equal(decrypts, 1);
  assert.equal(opened.row.metadata.read, true);
});
test("scope changes and foreign task/result metadata are rejected before any plaintext is returned", async () => {
  const row = { kind: "persistent", metadata: pm(), triggerKind: "legacy_unknown" },
    cache = new DisplayLru(10, 16000000);
  let decrypts = 0;
  const args = {
    row,
    workspace: {
      vault: { vaultId: "vault_A" },
      openPersistentResult: async () => {
        decrypts++;
        return content;
      },
    },
    api: async () => ({ metadata: { ...pm(), taskId: "task_B" } }),
    cache,
    scope: "owner_A",
    assert() {},
  };
  await assert.rejects(reader.readTaskResult(args), /invalid_response/);
  assert.equal(decrypts, 0);
  await assert.rejects(
    reader.readTaskResult({
      ...args,
      assert() {
        throw Error("cancelled");
      },
      api: async () => ({ metadata: pm() }),
    }),
    /cancelled/,
  );
  assert.equal(cache.size, 0);
});
test("result-state acknowledgements must match the immutable report, exact CAS increment and requested flags", () => {
  const row = { kind: "persistent", metadata: pm(), triggerKind: "manual" },
    ack = { ...pm(), stateVersion: 1, read: true };
  assert.equal(reader.stateReceipt(row, { read: true }, ack).metadata.read, true);
  for (const patch of [
    { taskId: "other" },
    { stateVersion: 2 },
    { starred: true },
    { read: false },
  ])
    assert.throws(() => reader.stateReceipt(row, { read: true }, { ...ack, ...patch }));
  assert.throws(() =>
    reader.resultPage({
      contractVersion: C,
      profile: "invented",
      items: [],
      nextCursor: null,
    }),
  );
});
