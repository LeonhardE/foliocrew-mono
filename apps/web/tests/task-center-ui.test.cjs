const assert = require("node:assert/strict"),
  test = require("node:test"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server"),
  { createTranslator } = require("next-intl");
const { compile } = require("./resource-library-helpers.cjs");
const { hooks, jsx: testJsx, all } = require("./resource-ui-harness.cjs");
function render({
  locale = "en",
  running = false,
  name = true,
  count = 0,
  home = false,
  modelPatch = {},
  resultPatch = {},
  workspacePatch = {},
  navigating = false,
  unreadPartial = false,
  trashOpen = false,
  centerPatch = {},
  nextOccurrence = null,
  interact,
  onRunViewChange,
} = {}) {
  const ui = interact ? hooks() : null;
  const messages = require(`../messages/${locale}.json`),
    metadata = { taskId: "task_PRIVATE_ID", status: "active", taskVersion: 1, executionEpoch: 1 };
  const mod = compile(
    "../components/TaskCenterPanel.tsx",
    {
      react: ui?.react ?? {
        ...React,
        useState: (initial) =>
          React.useState(trashOpen && initial === "browse" ? "trash" : initial),
      },
      "react/jsx-runtime": ui ? { jsx: testJsx, jsxs: testJsx } : require("react/jsx-runtime"),
      "next-intl": {
        useLocale: () => locale,
        useTranslations: (ns) =>
          createTranslator({
            locale,
            messages,
            namespace: ns,
            onError(error) {
              throw error;
            },
          }),
      },
      "@/lib/task-forms": { defaultTask: () => ({}) },
      "@/lib/task-center-schedule": { nextCenterOccurrence: () => nextOccurrence },
      "@/lib/task-types": { bindingKey: JSON.stringify },
      "./ReportDialog": { ReportDialog: () => null },
      "./WorkspaceFeedback": { InlineError: () => null, LoadingIndicator: () => null },
      "./TaskCenterPanel.module.css": {
        __esModule: true,
        default: new Proxy({}, { get: (_, p) => p }),
      },
    },
    { Intl, Date },
  );
  const model = {
    items: [metadata],
    taskNames: name ? { task_PRIVATE_ID: "Daily <brief>" } : {},
    nameErrors: {},
    selected: home ? null : metadata,
    form: home ? null : { name: "Daily <brief>", goal: "Summarize my watchlist" },
    owner: "owner_A",
    privateScope: "owner_A:vault_A:1",
    unlocked: true,
    listReady: true,
    loading: false,
    listError: "",
    error: "",
    canWrite: true,
    bindings: [],
    drafts: [],
    pendingOperations: [],
    catalogue: [],
    reload() {},
    ...modelPatch,
  };
  const center = {
    scope: "owner:vault:1",
    enabled: true,
    capabilityState: "ready",
    records: {},
    currentAssignments: [],
    executors: { status: "ready", providers: [] },
    manual: running
      ? {
          task_PRIVATE_ID: [
            {
              aggregate: { hasActiveExecutors: true },
              snapshot: { requestId: "request_PRIVATE_ID", executors: [] },
            },
          ],
        }
      : {},
    pending: null,
    ...centerPatch,
  };
  const props = {
    workspace: {
      authenticated: true,
      owner: "owner_A",
      phase: "unlocked",
      vault: { vaultId: "vault_A" },
      vaultGeneration: 1,
      ...workspacePatch,
    },
    model,
    center,
    navigating,
    resultState: {
      scope: "owner_A:vault_A:1",
      ready: true,
      complete: true,
      loading: false,
      error: "",
      partial: false,
      busy: false,
      ...resultPatch,
    },
    unreadCounts: { task_PRIVATE_ID: count },
    unreadPartial,
    results: "Results panel",
    onRunViewChange,
  };
  if (ui) {
    try {
      return interact(() => ui.render(() => mod.TaskCenterView(props)));
    } finally {
      ui.close();
    }
  }
  return renderToStaticMarkup(React.createElement(mod.TaskCenterView, props));
}
for (const locale of ["en", "zh", "zh-Hant"]) {
  test(`the ${locale} trash gives a named recoverable task separate restore and permanent-delete actions`, () => {
    const row = { taskId: "test-task", title: "My <brief>", canRestore: true };
    const messages = require(`../messages/${locale}.json`).taskCenter;
    const show = (rows) => render({ locale, trashOpen: true, centerPatch: { trash: rows } });
    const visible = show([row]);
    assert.ok(visible.includes("My &lt;brief&gt;"));
    for (const action of [messages.restore, messages.purge])
      assert.ok(visible.includes(">" + action + "</button>"));
    assert.ok(!show([{ ...row, title: null }]).includes(">" + messages.purge + "</button>"));
    assert.ok(!show([{ ...row, canRestore: false }]).includes(">" + messages.purge + "</button>"));
  });
  test(`the actual ${locale} task-list empty state resolves its message without translation fallback`, () => {
    const html = render({ locale, home: true, modelPatch: { items: [], taskNames: {} } });
    const messages = require(`../messages/${locale}.json`).taskCenter;
    assert.ok(html.includes(messages.noTasks));
    assert.ok(html.includes(messages.selectTaskHint));
    assert.doesNotMatch(html, /MISSING_MESSAGE|taskCenter\.|_PRIVATE/);
  });
  test(`the actual ${locale} task shows account run availability only after capabilities are confirmed`, () => {
    const messages = require(`../messages/${locale}.json`).taskCenter;
    const html = render({ locale, centerPatch: { enabled: false, capabilityState: "ready" } });
    assert.ok(html.includes(messages.runNotEnabled));
    for (const label of [messages.delete, messages.requestRun])
      assert.ok(html.includes(`disabled="">${label}</button>`), label);
    for (const capabilityState of ["loading", "error"])
      assert.ok(
        !render({ locale, centerPatch: { enabled: false, capabilityState } }).includes(
          messages.runNotEnabled,
        ),
        capabilityState,
      );
    assert.ok(!render({ locale }).includes(messages.runNotEnabled));
    assert.doesNotMatch(html, /MISSING_MESSAGE|taskCenter\.|HUB_|_PRIVATE/);
  });
  test(`the actual ${locale} task treats schedule math as a preview of an enabled Agent plan`, () => {
    const messages = require(`../messages/${locale}.json`).taskCenter;
    const schedule = {
      frequency: "daily",
      days: [],
      localTime: "22:00",
      timeZone: "America/Toronto",
    };
    const selectedRecord = { rules: { definition: { schedule } } };
    const nextOccurrence = "2026-11-24T03:00:00Z";
    const previewLabel = messages.schedulePreview.split("{date}")[0];
    const pending = render({ locale, nextOccurrence, centerPatch: { selectedRecord } });
    assert.match(pending, /22:00 · America\/Toronto/);
    assert.ok(pending.includes(messages.planUnconfirmed));
    assert.ok(!pending.includes(previewLabel));
    const confirmed = render({
      locale,
      nextOccurrence,
      centerPatch: {
        selectedRecord,
        currentAssignments: [
          {
            assignment: { assignmentId: "current", provider: "muse" },
            plan: { status: "enabled" },
          },
        ],
      },
    });
    assert.ok(confirmed.includes(messages.agentReportedPlan));
    assert.ok(confirmed.includes(previewLabel));
    assert.ok(!confirmed.includes(messages.planUnconfirmed));
  });
  test(`the actual ${locale} task view localizes unavailable names, original-save notices, drafts and unknown-error fallback`, () => {
    const messages = require(`../messages/${locale}.json`).taskCenter;
    const html = render({
      locale,
      home: true,
      name: false,
      count: 2,
      unreadPartial: true,
      modelPatch: {
        nameErrors: { task_PRIVATE_ID: "verification_failed" },
        error: "unknown_remote_PRIVATE",
        drafts: [{ slot: "new" }, { slot: "saved", taskId: "draft_PRIVATE_ID" }],
      },
      centerPatch: { pending: { taskId: "pending_PRIVATE_ID" } },
    });
    for (const label of [
      messages.nameUnavailable,
      messages.errors.request_failed,
      messages.unknownSave,
      messages.checkSave,
      messages.retryOriginal,
      messages.abandonSave,
      messages.newDraft,
      messages.savedDraft.replace("{number}", "2"),
      messages.unreadAtLeast.replace("{count}", "2"),
    ])
      assert.ok(html.includes(label), `${locale}: ${label}`);
    assert.doesNotMatch(html, /MISSING_MESSAGE|taskCenter\.|_PRIVATE/);
    assert.ok(render({ locale, name: false }).includes(messages.loadingName));
  });
}
test("task actions live inside the task and technical IDs never replace verified names", () => {
  const html = render();
  assert.match(html, /Daily &lt;brief&gt;/);
  assert.doesNotMatch(html, /task_PRIVATE_ID|request_PRIVATE_ID|Manage executors|View results/);
  assert.doesNotMatch(html.slice(0, html.indexOf("</header>")), /Request a run/);
  assert.match(html, /Request a run/);
});
test("Request a run requires verified status for this head and shows existing progress during recovery", () => {
  const record = { taskId: "task_PRIVATE_ID", taskVersion: 1, executionEpoch: 1 };
  const center = {
    runState: "ready",
    selectedRecord: record,
    currentAssignments: [{ assignment: { assignmentId: "current", provider: "muse" } }],
  };
  const disabled = /disabled="">Request a run<\/button>/;
  assert.doesNotMatch(render({ centerPatch: center }), disabled);
  for (const patch of [
    { runState: "loading" },
    { runState: "error" },
    { pending: { taskId: record.taskId } },
    { selectedRecord: { ...record, taskVersion: 2 } },
    { selectedRecord: { ...record, executionEpoch: 2 } },
    { currentAssignments: [] },
  ]) {
    assert.match(render({ centerPatch: { ...center, ...patch } }), disabled);
  }
  const running = render({ running: true, centerPatch: { ...center, runState: "error" } });
  assert.match(running, />View progress<\/button>/);
  assert.doesNotMatch(running, /disabled="">View progress<\/button>|>Request a run<\/button>/);
});
test("known running requests show a returnable progress action and list/title indicators", () => {
  const html = render({ running: true, count: 2 });
  assert.match(html, /View progress/);
  assert.equal((html.match(/aria-label="In progress"/g) || []).length, 2);
  assert.match(html, /2 unread results/);
  assert.doesNotMatch(render({ count: 0 }), /class="badge"/);
});
test("visible progress, results, and trash communicate the history they actually display", () => {
  const observed = [];
  render({
    running: true,
    centerPatch: { trash: [], trashList() {} },
    onRunViewChange(view) {
      observed.push(view);
    },
    interact(draw) {
      const button = (tree, label) =>
        all(tree, (n) => n.type === "button" && [n.props.children].flat().includes(label))[0];
      let tree = draw();
      assert.equal(observed.at(-1), "summary");
      button(tree, "View progress").props.onClick();
      tree = draw();
      assert.equal(observed.at(-1), "progress");
      all(tree, (n) => n.props?.id === "task-run-progress")[0].props.onClose();
      tree = draw();
      assert.equal(observed.at(-1), "summary");
      button(tree, "Results").props.onClick();
      tree = draw();
      assert.equal(button(tree, "Results").props["aria-selected"], true);
      assert.equal(observed.at(-1), "summary");
      button(tree, "Trash").props.onClick();
      draw();
      assert.equal(observed.at(-1), "hidden");
    },
  });
});
test("an unresolved task name has a skeleton rather than an opaque ID", () => {
  const html = render({ name: false });
  assert.match(html, /Loading task name/);
  assert.doesNotMatch(html, /task_PRIVATE_ID/);
});

test("legacy task settings wait for the selected assignment and retain it when details arrive", async () => {
  const { hooks, jsx, all } = require("./resource-ui-harness.cjs"),
    h = hooks();
  const messages = require("../messages/en.json");
  const mod = compile(
    "../components/TaskCenterPanel.tsx",
    {
      react: h.react,
      "react/jsx-runtime": { jsx, jsxs: jsx },
      "next-intl": {
        useLocale: () => "en",
        useTranslations: (ns) => createTranslator({ locale: "en", messages, namespace: ns }),
      },
      "@/lib/task-forms": { defaultTask: () => ({}) },
      "@/lib/task-center-schedule": { nextCenterOccurrence: () => nextOccurrence },
      "@/lib/task-types": { bindingKey: JSON.stringify },
      "./ReportDialog": { ReportDialog: () => null },
      "./WorkspaceFeedback": { InlineError: () => null, LoadingIndicator: () => null },
      "./TaskCenterPanel.module.css": {
        __esModule: true,
        default: new Proxy({}, { get: (_, p) => p }),
      },
    },
    { Intl, Date },
  );
  const meta = {
    taskId: "selected_legacy",
    status: "active",
    taskVersion: 1,
    envelopeFingerprint: "exact_version",
  };
  const model = {
    selected: meta,
    form: { name: "Legacy brief", goal: "Read selected resource" },
    items: [meta],
    taskNames: { selected_legacy: "Legacy brief" },
    nameErrors: {},
    canWrite: true,
    bindings: [],
    drafts: [],
    pendingOperations: [],
    catalogue: [],
  };
  const center = {
    scope: "owner:vault:1",
    enabled: true,
    records: { selected_legacy: { rules: null, assignments: [] } },
    currentAssignments: [],
    manual: {},
    pending: null,
  };
  center.selectedRecord = center.records.selected_legacy;
  center.executors = { status: "loading", providers: [] };
  let retries = 0;
  center.retryExecutors = () => {
    retries++;
    center.executors = { status: "ready", providers: ["muse"] };
  };
  const persistent = {
    loaded: true,
    views: [],
    tasks: [],
    loadTask() {
      assert.fail("display reloaded the task");
    },
  };
  const draw = () =>
    h.render(() => mod.TaskCenterView({ workspace: {}, model, center, persistent }));
  const settings = (tree) =>
    all(tree, (n) => n.type === "button" && n.props.children === "Settings")[0];
  const fields = (tree) => all(tree, (n) => n.type === "dd");
  try {
    let tree = draw();
    assert.equal(settings(tree).props.disabled, true);
    assert.ok(
      fields(tree).some(
        (field) => field.props.children?.props?.busy && field.props.children?.props?.hasContent,
      ),
    );
    center.executors = { status: "error", providers: [] };
    tree = draw();
    const errorField = fields(tree).find((field) => field.props.children?.props?.onRetry);
    assert.equal(
      errorField.props.children.props.message,
      messages.taskCenter.errors.request_failed,
    );
    assert.equal(
      all(tree, (n) => n.props?.message === messages.taskCenter.errors.request_failed).length,
      1,
    );
    assert.equal(settings(tree).props.disabled, true);
    errorField.props.children.props.onRetry();
    tree = draw();
    assert.equal(retries, 1);
    assert.equal(settings(tree).props.disabled, false);
    assert.ok(fields(tree).some((field) => field.props.children === "Muse"));
  } finally {
    h.close();
  }
});

test("resource handoffs wait for the catalogue and review resources without freshness controls", () => {
  const { hooks, jsx, all } = require("./resource-ui-harness.cjs"),
    h = hooks();
  let started = 0,
    consumed = 0;
  const model = {
    items: [],
    taskNames: {},
    nameErrors: {},
    selected: null,
    form: null,
    canWrite: true,
    bindings: [],
    drafts: [],
    pendingOperations: [],
    catalogue: [],
    catalogueReady: false,
    catalogueLoading: true,
    startNew(seed, form) {
      assert.equal(seed, request.binding);
      started++;
      model.form = form;
    },
    setForm(form) {
      model.form = form;
    },
    reloadCatalogue() {},
  };
  const request = { owner: "owner_A", nonce: 1, binding: { ref: { kind: "watchlist" } } };
  const center = {
    scope: "owner_A:vault_A:1",
    enabled: true,
    records: {},
    currentAssignments: [],
    manual: {},
    pending: null,
  };
  const LoadingIndicator = () => null,
    InlineError = () => null;
  const mod = compile(
    "../components/TaskCenterPanel.tsx",
    {
      react: h.react,
      "react/jsx-runtime": { jsx, jsxs: jsx },
      "next-intl": { useLocale: () => "en", useTranslations: () => (v) => v },
      "@/lib/task-forms": {
        defaultTask: () => ({
          outputSpec: {},
          inputPolicy: {
            allowPartial: false,
            allowUnknownAsOf: false,
            maxFetchedAgeSeconds: 86400,
          },
        }),
      },
      "@/lib/task-center-schedule": { nextCenterOccurrence: () => nextOccurrence },
      "@/lib/task-types": { bindingKey: JSON.stringify },
      "./ReportDialog": { ReportDialog: () => null },
      "./WorkspaceFeedback": { LoadingIndicator, InlineError },
      "./TaskCenterPanel.module.css": {
        __esModule: true,
        default: { advancedOptions: "advancedOptions" },
      },
    },
    { Intl, Date },
  );
  const draw = () =>
    h.render(() =>
      mod.TaskCenterView({
        workspace: { owner: "owner_A" },
        model,
        center,
        request,
        onRequestConsumed: () => consumed++,
      }),
    );
  let tree = draw();
  assert.equal(started, 0);
  assert.ok(all(tree, (n) => n.type?.name === "LoadingIndicator" && n.props.busy).length);
  model.catalogueLoading = false;
  model.catalogueError = "source_unavailable";
  tree = draw();
  assert.equal(started, 0);
  assert.ok(all(tree, (n) => n.type?.name === "InlineError" && n.props.onRetry).length);
  model.catalogueError = "";
  model.catalogueReady = true;
  draw();
  assert.equal(started, 1);
  assert.equal(consumed, 1);
  model.setForm({ ...model.form, name: "Synthetic task", goal: "Use only the test resource" });
  const next = (view) => all(view, (n) => n.type === "button" && n.props.children === "next")[0];
  const details = all(
    draw(),
    (n) => n.type === "details" && n.props.className === "advancedOptions",
  )[0];
  assert.ok(
    all(details, (n) => n.type === "label" && n.props.children.includes("reportLanguage")).length,
  );
  const assertNoRules = (view) => {
    for (const label of ["inputPolicy", "unknownAsOf", "partial", "maxAge"])
      assert.equal(all(view, (n) => [n.props.children].flat().includes(label)).length, 0);
    assert.ok(all(view, (n) => n.props.children === "resources").length);
  };
  next(draw()).props.onClick();
  assertNoRules(draw());
  next(draw()).props.onClick();
  assertNoRules(draw());
  h.close();
});

test("only the task-list homepage reports ready after current lists names capabilities and complete report feeds", () => {
  const state = (options = {}) => {
    const html = render({ home: true, ...options });
    return html.slice(0, html.indexOf(">") + 1);
  };
  assert.match(state({ count: 2 }), /data-load-scope="task-list" data-load-state="ready"/);
  for (const options of [
    { modelPatch: { items: [], listReady: false } },
    { name: false },
    { modelPatch: { loading: true } },
    { resultPatch: { loading: true, complete: false } },
    { resultPatch: { ready: false, complete: false } },
    { centerPatch: { capabilityState: "loading", enabled: false } },
  ]) {
    assert.match(state(options), /data-load-state="loading"/);
    assert.doesNotMatch(state(options), /data-load-state="ready"/);
  }
  for (const options of [
    { modelPatch: { listError: "service_unavailable" } },
    { modelPatch: { nameErrors: { task_PRIVATE_ID: "verification_failed" } } },
    { resultPatch: { error: "service_unavailable" } },
    { resultPatch: { partial: true } },
    { centerPatch: { capabilityState: "error" } },
  ])
    assert.match(state(options), /data-load-state="error"/);
  assert.match(
    state({ centerPatch: { capabilityState: "ready", enabled: false } }),
    /data-load-state="ready"/,
  );
  assert.match(state({ modelPatch: { items: [], taskNames: {} } }), /data-load-state="ready"/);
  for (const options of [
    { workspacePatch: { owner: "owner_B" } },
    { workspacePatch: { vaultGeneration: 2 } },
    { workspacePatch: { needsDeviceApproval: true } },
    { resultPatch: { scope: "owner_B:vault_A:1" } },
  ])
    assert.match(state(options), /data-load-state="locked"/);
  assert.doesNotMatch(render(), /data-load-scope|data-load-state/);
  assert.doesNotMatch(state({ navigating: true }), /data-load-scope|data-load-state/);
  assert.doesNotMatch(state(), /PRIVATE|owner_A|vault_A/);
});
