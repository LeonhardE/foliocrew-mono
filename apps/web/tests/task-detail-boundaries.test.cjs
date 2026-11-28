const test = require("node:test");
const assert = require("node:assert/strict");
const { stack, response, CONTRACT } = require("./full-flow-boundaries-helpers.cjs");
const { packet, metadata } = require("./task-overview-fixtures.cjs");
const { readTaskDetail } = require("./task-overview-helpers.cjs").detail;
const ready = (data) => ({ status: "ready", data });
const path = "/api/v3/task-center/vault_A/tasks/task_1/detail/query";
const body = { contractVersion: CONTRACT, includePacket: true, includeAttribution: false };
const render = () => ({
  contractVersion: CONTRACT,
  profile: "folioview.owner-task-detail.v1",
  state: {
    contractVersion: CONTRACT,
    profile: "folioview.task-center.v1",
    taskId: "task_1",
    taskVersion: 1,
    executionEpoch: 1,
    rules: null,
    assignments: [],
    dispatchSupported: false,
    nativeScheduleAttested: false,
  },
  packet: ready(packet(metadata(1))),
  legacy: null,
  attribution: null,
});
test("the owner detail query makes one read and accepts only the requested task and sections", async (t) => {
  const b = await stack();
  t.after(() => b.close());
  const owner = b.mount();
  await owner.login("synthetic_detail_owner");
  let next = render();
  b.setUpstream(() => response(next));
  const send = (route, opts) =>
    owner.value.requestPrivate("agent-hub", route, owner.value.sessionKey, opts);
  const detail = await readTaskDetail(
    send,
    "vault_A",
    "task_1",
    true,
    false,
    new AbortController().signal,
  );
  assert.equal(detail.packet.data.metadata.taskId, "task_1");
  assert.equal(b.producerCalls().length, 1);
  const post = (json) => send(path, { method: "POST", json });
  await assert.rejects(post({ ...body, includePacket: 1 }));
  await assert.rejects(post({ ...body, scope: "unexpected" }));
  assert.equal(b.producerCalls().length, 1);
  for (const change of [
    (v) => {
      v.packet.data.metadata.taskId = "task_2";
    },
    (v) => {
      v.state.executionEpoch++;
    },
    (v) => {
      v.packet.data.keyProofs.extra = "unexpected";
    },
    (v) => {
      v.legacy = { status: "error" };
    },
    (v) => {
      v.attribution = { status: "unavailable" };
    },
  ]) {
    next = render();
    change(next);
    assert.equal((await post(body)).status, 503);
  }
  next = render();
  next.packet = { status: "unavailable" };
  next.legacy = ready({
    contractVersion: CONTRACT,
    profile: "folioview.persistent-content.v1",
    authority: null,
    envelope: null,
  });
  assert.equal((await post(body)).status, 200);
});

test("only an explicit vault request can carry the original vault response and matching full task metadata", async (t) => {
  const b = await stack();
  t.after(() => b.close());
  const owner = b.mount();
  await owner.login("synthetic_detail_owner");
  const vault = {
    contractVersion: CONTRACT,
    vault: {
      vaultId: "vault_A",
      rootJwk: { kty: "EC", crv: "P-256", x: "A".repeat(43), y: "A".repeat(43) },
      rootKeyId: "root_A",
      registryHistory: [],
      archive: null,
      version: 1,
    },
    sources: [],
  };
  const payload = () => ({
    ...render(),
    taskMetadata: metadata(1),
    vaultResponse: ready(structuredClone(vault)),
  });
  let next = payload();
  b.setUpstream(() => response(next));
  const send = (route, opts) =>
    owner.value.requestPrivate("agent-hub", route, owner.value.sessionKey, opts);
  const full = { ...body, includeVault: true };
  const post = (json) => send(path, { method: "POST", json });
  const read = await readTaskDetail(
    send,
    "vault_A",
    "task_1",
    true,
    false,
    new AbortController().signal,
    true,
  );
  assert.equal(read.vaultResponse.status, "ready");
  assert.equal(read.taskMetadata.envelopeFingerprint, metadata(1).envelopeFingerprint);
  assert.equal((await post(body)).status, 503);
  await assert.rejects(post({ ...full, includeVault: false }));
  for (const change of [
    (v) => {
      delete v.taskMetadata;
    },
    (v) => {
      v.vaultResponse = null;
    },
    (v) => {
      v.vaultResponse.data.vault.vaultId = "another_vault";
    },
    (v) => {
      v.vaultResponse.data.vault.rootJwk.d = "invalid_field";
    },
    (v) => {
      v.taskMetadata.deliveryRevision++;
    },
  ]) {
    next = payload();
    change(next);
    assert.equal((await post(full)).status, 503);
  }
  next = payload();
  next.vaultResponse = { status: "unavailable" };
  assert.equal((await post(full)).status, 200);
});

test("the selected task control carrier validates its request, authenticated subject, task state and manual summaries", async (t) => {
  const { createHash } = require("node:crypto");
  const { controls } = require("./task-overview-fixtures.cjs");
  const { TASK_CONTROLS_REQUEST } = require("./task-overview-helpers.cjs").detail;
  const uid = "synthetic_control_owner";
  const subject = createHash("sha256").update(uid).digest("hex");
  const b = await stack();
  t.after(() => b.close());
  const owner = b.mount();
  await owner.login(uid);
  const post = (json) =>
    owner.value.requestPrivate("agent-hub", path, owner.value.sessionKey, { method: "POST", json });
  let next = controls("task_1", subject, true);
  b.setUpstream(() => response(next));
  assert.equal((await post(TASK_CONTROLS_REQUEST)).status, 200);
  for (const change of [
    { includePacket: true },
    { includeAttribution: true },
    { includeVault: true },
    { includeManual: false },
    { extra: 1 },
  ])
    await assert.rejects(post({ ...TASK_CONTROLS_REQUEST, ...change }));
  assert.equal(b.producerCalls().length, 1);
  for (const corrupt of [
    (v) => {
      v.manual.items[0].snapshot.ownerSubject = "other_owner";
    },
    (v) => {
      v.manual.items[0].snapshot.taskId = "other_task";
    },
    (v) => {
      v.manual.items[0].snapshot.vaultId = "other_vault";
    },
    (v) => {
      v.manual.items[0].aggregate.hasActiveExecutors = true;
    },
    (v) => {
      v.manual.items = [{}];
    },
    (v) => {
      v.manual.items.push(v.manual.items[0]);
    },
    (v) => {
      v.state.taskId = "other_task";
    },
    (v) => {
      v.legacy = null;
    },
  ]) {
    next = controls("task_1", subject, true);
    corrupt(next);
    assert.equal((await post(TASK_CONTROLS_REQUEST)).status, 503);
  }
});
