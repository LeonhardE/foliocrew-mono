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
