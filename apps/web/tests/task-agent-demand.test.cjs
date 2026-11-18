const assert = require("node:assert/strict"),
  test = require("node:test");
const { compile } = require("./resource-library-helpers.cjs");
const { hooks, jsx, all } = require("./resource-ui-harness.cjs");

test("real TasksPanel requests executors only for creation and editing while preserving full list and unread reads", () => {
  const h = hooks(),
    demands = [],
    resultReads = [],
    taskReads = [],
    catalogueDemand = [],
    resultPageDemand = [],
    selectedHeads = [];
  let active = true;
  const workspace = { authenticated: true, owner: "owner_A", phase: "unlocked" };
  const model = { owner: "owner_A", unlocked: true, selected: null, form: null, openTask() {} };
  const results = { unreadCounts: { task_A: 7 }, partial: true, detail: null };
  const TaskCenterView = () => null;
  const { default: TasksPanel } = compile(
    "../components/TasksPanel.tsx",
    {
      react: h.react,
      "react/jsx-runtime": { jsx, jsxs: jsx },
      "next-intl": { useLocale: () => "en", useTranslations: () => (v) => v },
      "./useTasks": {
        useTasks: (_workspace, options) => {
          taskReads.push(options.active);
          catalogueDemand.push(options.catalogueRequested);
          return model;
        },
      },
      "./useTaskCenter": {
        useTaskCenter: (_workspace, _active, head) => {
          selectedHeads.push(head);
          return { manual: {} };
        },
      },
      "./useTaskResults": {
        useTaskResults: (
          _workspace,
          _persistent,
          _model,
          enabled,
          _observed,
          _center,
          _overview,
          resultsVisible,
        ) => {
          resultPageDemand.push(resultsVisible);
          resultReads.push(enabled);
          return results;
        },
      },
      "./TaskResultsPanel": { TaskResultsPanel: () => null },
      "./TaskCenterPanel": { TaskCenterView },
      "./PasskeyHelp": { PasskeyHelp: () => null },
      "@/lib/task-forms": { defaultTask: () => ({}) },
      "@/lib/task-types": { bindingKey: JSON.stringify },
      "./TasksPanel.module.css": { __esModule: true, default: {} },
    },
    { window: { location: { hash: "" }, addEventListener() {}, removeEventListener() {} } },
  );
  const onAgentConnectionsNeeded = (needed) => demands.push(needed);
  const draw = () => h.render(() => TasksPanel({ workspace, active, onAgentConnectionsNeeded }));
  let tree = draw();
  assert.equal(demands.at(-1), false);
  assert.equal(resultReads.at(-1), true);
  assert.equal(taskReads.at(-1), true);
  assert.equal(
    all(tree, (n) => n.type === TaskCenterView)[0].props.unreadCounts,
    results.unreadCounts,
  );
  assert.equal(all(tree, (n) => n.type === TaskCenterView)[0].props.unreadPartial, true);
  model.form = { name: "New task" };
  draw();
  assert.equal(demands.at(-1), true, "new task executor selection is enabled");
  active = false;
  draw();
  assert.equal(demands.at(-1), false);
  active = true;
  draw();
  assert.equal(demands.at(-1), true, "returning draft retains demand");
  model.selected = { taskId: "task_A" };
  model.dirty = true;
  draw();
  assert.equal(demands.at(-1), true, "editing preserves executor demand");
  model.dirty = false;
  draw();
  assert.equal(
    demands.at(-1),
    false,
    "browsing the selected task does not discover Agent connections",
  );
  assert.equal(catalogueDemand.at(-1), false);
  assert.equal(resultPageDemand.at(-1), false);
  model.opening = { taskId: "task_B" };
  model.selected = null;
  draw();
  assert.equal(
    selectedHeads.at(-1),
    model.opening,
    "prefetch the selected head while its body is opening",
  );
  model.opening = null;
  model.selected = { taskId: "task_A" };
  const resultsVisible = all(draw(), (n) => n.type === TaskCenterView)[0].props.results.props
    .onVisibleChange;
  resultsVisible(true);
  draw();
  assert.equal(resultPageDemand.at(-1), true);
  resultsVisible(false);
  const edit = all(draw(), (n) => n.type === TaskCenterView)[0].props.onEditingChange;
  edit(true);
  draw();
  assert.equal(catalogueDemand.at(-1), true);
  assert.equal(demands.at(-1), true, "opening settings loads the editor's eligible connections");
  edit(false);
  draw();
  assert.equal(demands.at(-1), false);
  model.form = null;
  model.selected = null;
  draw();
  assert.equal(demands.at(-1), false);
  model.form = { name: "OLD" };
  workspace.owner = "owner_B";
  draw();
  assert.equal(demands.at(-1), false);
  workspace.owner = "owner_A";
  draw();
  assert.equal(demands.at(-1), true);
  h.close();
  assert.equal(demands.at(-1), false, "unmount releases display demand");
});
