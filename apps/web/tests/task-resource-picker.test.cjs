const assert = require("node:assert/strict"),
  test = require("node:test");
const { createTranslator } = require("next-intl");
const { compile } = require("./resource-library-helpers.cjs");
const { hooks, jsx, all } = require("./resource-ui-harness.cjs");
const types = compile("../lib/task-types.ts");
const forms = compile("../lib/task-forms.ts", { "./task-types": types });
const ref = (kind, id) => ({
  kind,
  sourceService: kind === "holdings" ? "portfolio" : "user",
  resourceId: id,
  incarnation: "incarnation_A",
});
const refs = Array.from({ length: 4 }, (_, i) => ref("holdings", "holdings_" + i));
const savedBinding = { ref: refs[1], sourceEpoch: 1 };
function catalogue(mode = "unavailable") {
  return {
    contractVersion: types.TASK_CONTRACT,
    profile: "folioview.owner-resource-discovery.v1",
    readAt: "2026-11-17T00:00:00Z",
    groups: [
      {
        kind: "holdings",
        sourceService: "portfolio",
        status:
          mode === "partial" ? "partial" : mode === "unavailable" ? "unavailable" : "available",
        items: refs.map((r, i) => {
          const unavailable = mode === "unavailable" || (mode === "partial" && i === 1);
          return {
            ref: r,
            revision: unavailable || mode === "pending" ? null : 1,
            sourceEpoch: unavailable ? null : 1,
            state: unavailable ? "unavailable" : mode === "pending" ? "pending" : "active",
            snapshotId: unavailable || mode === "pending" ? null : "snapshot_" + i,
            updatedAt: null,
            encryptedEvidence: "not_checked",
          };
        }),
      },
      {
        kind: "watchlist",
        sourceService: "user",
        status: "available",
        items: [
          {
            ref: ref("watchlist", "watchlist_A"),
            revision: 1,
            sourceEpoch: 1,
            state: "ready",
            snapshotId: null,
            updatedAt: "2026-11-17T00:00:00Z",
            encryptedEvidence: "not_prepared",
          },
        ],
      },
      {
        kind: "channel_follows",
        sourceService: "user",
        status: "available",
        items: [
          {
            ref: null,
            revision: null,
            sourceEpoch: null,
            state: "uninitialized",
            snapshotId: null,
            updatedAt: null,
            encryptedEvidence: "not_prepared",
          },
        ],
      },
    ],
  };
}
const text = (n) =>
  typeof n === "string" || typeof n === "number"
    ? String(n)
    : Array.isArray(n)
      ? n.map(text).join("")
      : n && typeof n === "object"
        ? text(n.props?.children)
        : "";
function picker({
  locale = "en",
  mode = "unavailable",
  credential = "active",
  schedule = null,
  setup,
} = {}) {
  const h = hooks(),
    messages = require("../messages/" + locale + ".json");
  let retries = 0,
    changes = 0;
  const InlineError = () => null,
    LoadingIndicator = () => null;
  const component = compile(
    "../components/TaskCenterPanel.tsx",
    {
      react: h.react,
      "react/jsx-runtime": { jsx, jsxs: jsx },
      "next-intl": {
        useLocale: () => locale,
        useTranslations: (ns) =>
          createTranslator({
            locale,
            messages,
            namespace: ns,
            onError: (e) => {
              throw e;
            },
          }),
      },
      "@/lib/task-forms": forms,
      "@/lib/task-center-schedule": { nextCenterOccurrence: () => null },
      "@/lib/task-types": types,
      "./ReportDialog": { ReportDialog: () => null },
      "./WorkspaceFeedback": { InlineError, LoadingIndicator },
      "./TaskCenterPanel.module.css": { __esModule: true, default: {} },
    },
    { Intl, Date },
  );
  const meta = { taskId: "task_A", status: "active", taskVersion: 1 };
  const model = {
    owner: "owner_A",
    privateScope: "owner_A:vault_A:1",
    unlocked: true,
    selected: meta,
    items: [meta],
    taskNames: { task_A: "Synthetic task" },
    nameErrors: {},
    form: { ...forms.defaultTask("custom"), name: "Synthetic task", goal: "Synthetic test" },
    canWrite: true,
    bindings: structuredClone([savedBinding]),
    drafts: [],
    pendingOperations: [],
    catalogue: types.taskCatalogue(catalogue(mode)),
    catalogueReady: true,
    catalogueLoading: false,
    catalogueError: "",
    error: "",
    reloadCatalogue() {
      retries++;
    },
    setBindings(v) {
      changes++;
      model.bindings = v;
    },
  };
  const center = {
    scope: "owner_A:vault_A:1",
    enabled: true,
    capabilityState: "ready",
    selectedRecord: { rules: { definition: { schedule } }, assignments: [] },
    currentAssignments: [],
    executors: { status: "ready", providers: [] },
    manual: {},
    pending: null,
  };
  const persistent = {
    loaded: true,
    loading: false,
    tasks: [],
    views: [
      {
        connection: { provider: "chatgpt", status: "active" },
        credential: { status: credential },
        tasks: [],
      },
    ],
  };
  const workspace = {
    authenticated: true,
    owner: "owner_A",
    phase: "unlocked",
    vault: { vaultId: "vault_A" },
    vaultGeneration: 1,
  };
  setup?.({ model, center, persistent, workspace });
  const draw = () =>
    h.render(() =>
      component.TaskCenterView({
        workspace,
        model,
        center,
        persistent,
      }),
    );
  const button = (tree, label) =>
    all(tree, (n) => n.type === "button" && n.props.children === label)[0];
  let tree = draw();
  button(tree, messages.taskCenter.settings).props.onClick();
  tree = draw();
  button(tree, messages.taskCenter.next).props.onClick();
  const rows = (tree) => {
    const field = all(
      tree,
      (n) =>
        n.type === "fieldset" &&
        all(n, (c) => c.type === "legend" && c.props.children === messages.taskCenter.resources)
          .length,
    )[0];
    return all(field, (n) => n.type === "label");
  };
  return {
    draw,
    model,
    center,
    messages: messages.taskCenter,
    rows,
    InlineError,
    LoadingIndicator,
    button,
    close: h.close,
    retries: () => retries,
    changes: () => changes,
  };
}
for (const locale of ["en", "zh", "zh-Hant"])
  test(
    "unavailable holdings remain visible with retained selection and local retry in " + locale,
    () => {
      const p = picker({ locale });
      try {
        let tree = p.draw(),
          holdings = p.rows(tree).filter((n) => text(n).includes(p.messages.kinds.holdings));
        assert.equal(holdings.length, 4);
        const inputs = holdings.flatMap((n) => all(n, (c) => c.type === "input"));
        assert.ok(inputs.every((n) => n.props.disabled));
        assert.equal(inputs.filter((n) => n.props.checked).length, 1);
        assert.ok(holdings.every((n) => text(n).includes(p.messages.resourceNotSelectable)));
        const notice = all(
          tree,
          (n) =>
            n.type?.name === "InlineError" &&
            n.props.message === p.messages.resourceCataloguePartial,
        );
        assert.equal(notice.length, 1);
        assert.equal(p.retries(), 0);
        const renderedNotice = notice[0].type(notice[0].props);
        assert.equal(renderedNotice.props.role, "alert");
        assert.ok(text(renderedNotice).includes(p.messages.resourceCataloguePartial));
        all(renderedNotice, (n) => n.type === "button")[0].props.onClick();
        assert.equal(p.retries(), 1);
        inputs[1].props.onChange({ target: { checked: false } });
        assert.equal(p.changes(), 0);
        assert.deepEqual(JSON.parse(JSON.stringify(p.model.bindings)), [savedBinding]);
        assert.ok(
          p.model.catalogue
            .filter((o) => o.kind === "holdings")
            .every((o) => o.binding === null && !o.selectable),
        );
        p.model.catalogue = types.taskCatalogue(catalogue("available"));
        tree = p.draw();
        const recovered = p.rows(tree).filter((n) => text(n).includes(p.messages.kinds.holdings));
        assert.equal(recovered.length, 4);
        const recoveredInputs = recovered.flatMap((n) => all(n, (c) => c.type === "input"));
        assert.ok(recoveredInputs.every((n) => !n.props.disabled));
        assert.equal(recoveredInputs.filter((n) => n.props.checked).length, 1);
        assert.equal(all(tree, (n) => n.type?.name === "InlineError").length, 0);
        assert.equal(p.changes(), 0, "successful discovery does not rewrite saved bindings");
        p.button(tree, p.messages.next).props.onClick();
        tree = p.draw();
        assert.ok(
          all(tree, (n) => n.type === "dd" && text(n) === p.messages.kinds.holdings).length,
        );
      } finally {
        p.close();
      }
    },
  );
test("partial discovery keeps healthy choices and does not remove the unavailable saved binding", () => {
  const p = picker({ mode: "partial" });
  try {
    const tree = p.draw(),
      rows = p.rows(tree),
      inputs = rows.flatMap((n) => all(n, (c) => c.type === "input"));
    assert.equal(rows.filter((n) => text(n).includes(p.messages.kinds.holdings)).length, 4);
    assert.equal(inputs.filter((n) => !n.props.disabled).length, 4);
    assert.ok(inputs[1].props.checked && inputs[1].props.disabled);
    inputs[4].props.onChange({ target: { checked: true } });
    assert.equal(p.changes(), 1);
    assert.equal(p.model.bindings.length, 2);
    assert.deepEqual(JSON.parse(JSON.stringify(p.model.bindings[0])), savedBinding);
  } finally {
    p.close();
  }
});
test("loading and transport failure do not masquerade as ready partial discovery or permit new choices", () => {
  const p = picker({ mode: "available" });
  try {
    for (const flags of [
      { catalogueLoading: true, catalogueError: "" },
      { catalogueLoading: false, catalogueError: "source_unavailable" },
    ]) {
      Object.assign(p.model, flags);
      const tree = p.draw(),
        inputs = p.rows(tree).flatMap((n) => all(n, (c) => c.type === "input"));
      assert.ok(inputs.every((n) => n.props.disabled));
      inputs[4].props.onChange({ target: { checked: true } });
      assert.equal(p.changes(), 0);
      assert.equal(
        all(
          tree,
          (n) =>
            n.type?.name === "InlineError" &&
            n.props.message === p.messages.resourceCataloguePartial,
        ).length,
        0,
      );
    }
  } finally {
    p.close();
  }
});
test("available and pending holdings remain independent of Agent credential status", () => {
  for (const mode of ["available", "pending"])
    for (const credential of ["active", "revoked"]) {
      const p = picker({ mode, credential });
      try {
        const tree = p.draw(),
          rows = p.rows(tree).filter((n) => text(n).includes(p.messages.kinds.holdings));
        assert.equal(rows.length, 4);
        assert.equal(
          all(
            tree,
            (n) =>
              n.type?.name === "InlineError" &&
              n.props.message === p.messages.resourceCataloguePartial,
          ).length,
          0,
        );
        assert.ok(
          rows
            .flatMap((n) => all(n, (c) => c.type === "input"))
            .every((n) => Boolean(n.props.disabled) === (mode === "pending")),
        );
      } finally {
        p.close();
      }
    }
});
test("display reference does not invent a binding or relax catalogue validation", () => {
  const input = catalogue(),
    options = types.taskCatalogue(input);
  assert.deepEqual(JSON.parse(JSON.stringify(options[1].ref)), refs[1]);
  assert.equal(options[1].binding, null);
  assert.equal(options[1].selectable, false);
  for (const mutate of [
    (v) => (v.groups[0].items[0].ref.extra = true),
    (v) => (v.groups[0].items[0].sourceEpoch = 0),
    (v) => (v.groups[0].items[0].sourceEpoch = true),
  ]) {
    const value = structuredClone(catalogue());
    mutate(value);
    assert.throws(
      () => types.taskCatalogue(value),
      (e) => e.code === "invalid_response",
    );
  }
});

for (const newTask of [false, true]) {
  test(`saving a ${newTask ? "new" : "modified"} schedule after viewing a signed rule submits only editable fields`, async () => {
    const p = picker({
      schedule: {
        frequency: "weekly",
        days: [2, 4],
        localTime: "22:00",
        timeZone: "America/Toronto",
        effectiveFrom: 1795489200,
        graceMinutes: 60,
        dstGap: "skip",
        dstFold: "first",
      },
    });
    try {
      if (newTask) {
        p.model.startNew = () => {
          p.model.selected = null;
        };
        p.button(p.draw(), p.messages.new).props.onClick();
        p.button(p.draw(), p.messages.next).props.onClick();
        p.button(p.draw(), p.messages.scheduled).props.onClick();
      }
      const time = all(p.draw(), (n) => n.type === "input" && n.props.type === "time")[0];
      time.props.onChange({ target: { value: "15:21" } });
      p.button(p.draw(), p.messages.next).props.onClick();
      if (newTask) {
        p.model.selected = {
          taskId: "task_B",
          taskVersion: 1,
          executionEpoch: 1,
          status: "active",
        };
        p.center.selectedRecord = { rules: null, assignments: [] };
      }
      const commands = [];
      p.center.base = (taskId) => taskId;
      p.center.api = async () => p.center.selectedRecord;
      p.center.command = async (taskId, action, schedule) => {
        commands.push({ taskId, action, schedule });
      };
      p.center.load = async () => {};
      p.button(p.draw(), p.messages.confirm).props.onClick();
      await new Promise((resolve) => setImmediate(resolve));
      assert.deepEqual(JSON.parse(JSON.stringify(commands)), [
        {
          taskId: newTask ? "task_B" : "task_A",
          action: "set_rules",
          schedule: {
            frequency: newTask ? "daily" : "weekly",
            days: newTask ? [] : [2, 4],
            localTime: "15:21",
            timeZone: "America/Toronto",
          },
        },
      ]);
    } finally {
      p.close();
    }
  });
}

for (const [scenario, expected] of [
  ["reschedule", ["set_rules", "set_assignment"]],
  ["same schedule", []],
  ["initially stale", ["set_rules"]],
  ["deselect", ["set_rules", "remove_assignment"]],
  ["concurrent replacement", ["set_rules"]],
]) {
  test(`saving a task with an existing Muse assignment: ${scenario}`, async () => {
    const commands = [];
    const p = picker({
      mode: "available",
      schedule: { frequency: "daily", days: [], localTime: "15:37", timeZone: "America/Toronto" },
      setup({ model, center, persistent, workspace }) {
        const state = center.selectedRecord;
        const d = state.rules.definition;
        const versions = { taskVersion: 1, executionEpoch: 1, ruleVersion: 2, lifecycleEpoch: 1 };
        Object.assign(d, versions);
        Object.assign(model.selected, { executionEpoch: 1, vaultId: "vault_A" });
        const credential = { connectionId: "muse_connection" };
        const row = {
          assignment: {
            ...versions,
            ruleVersion: scenario === "initially stale" ? 1 : 2,
            assignmentId: "original_muse",
            assignmentVersion: 1,
            credential,
            provider: "muse",
            status: "active",
            authorityFingerprint: "same_publication",
          },
          plan: { currentAssignment: scenario !== "initially stale" },
        };
        state.assignments = [row];
        center.currentAssignments = row.plan.currentAssignment ? [row] : [];
        center.executors.providers = row.plan.currentAssignment ? ["muse"] : [];
        center.base = (id) => id;
        center.api = async () => state;
        center.load = async () => {};
        center.command = async (id, action, value, reviewed) => {
          assert.equal(reviewed, state);
          commands.push(action);
          if (action === "set_rules") {
            d.schedule = value;
            d.ruleVersion++;
            row.plan.currentAssignment = false;
          } else if (action === "remove_assignment")
            assert.equal(value, row.assignment.assignmentId);
          else assert.equal(value.authorityFingerprint, row.assignment.authorityFingerprint);
        };
        workspace.verifyTaskCenterState = async (current) => current;
        persistent.views = [
          {
            connection: { provider: "muse", status: "active", ...credential },
            credential: { status: "active", reference: credential },
          },
        ];
        const controller = {
          async approveTask(connection, selected, { beforePublish }) {
            await beforePublish(
              { kind: "no_change", authority: { fingerprint: "same_publication" } },
              {},
            );
          },
        };
        persistent.executeTaskActivation = (run) =>
          run(
            controller,
            async () => ({ slot: { currentCredential: credential } }),
            () => {},
          );
      },
    });
    try {
      const muse = all(p.draw(), (n) => n.type === "label" && text(n) === "Muse")[0];
      const input = all(muse, (n) => n.type === "input")[0];
      assert.equal(input.props.checked, scenario !== "initially stale");
      if (scenario === "deselect" || scenario === "concurrent replacement")
        input.props.onChange({ target: { checked: false } });
      if (scenario === "concurrent replacement")
        p.center.selectedRecord.assignments[0].assignment.assignmentVersion++;
      if (scenario !== "same schedule") {
        const time = all(p.draw(), (n) => n.type === "input" && n.props.type === "time")[0];
        time.props.onChange({ target: { value: "14:37" } });
      }
      p.button(p.draw(), p.messages.next).props.onClick();
      p.button(p.draw(), p.messages.confirm).props.onClick();
      await new Promise((resolve) => setImmediate(resolve));
      assert.deepEqual(commands, expected);
      if (scenario === "concurrent replacement") {
        assert.ok(
          all(p.draw(), (node) => node.props?.message === p.messages.errors.version_conflict)
            .length,
        );
      } else assert.ok(p.button(p.draw(), p.messages.settings));
    } finally {
      p.close();
    }
  });
}
