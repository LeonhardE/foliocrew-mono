const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const React = require("react");
const jsxRuntime = require("react/jsx-runtime");
const { renderToStaticMarkup } = require("react-dom/server");
const { createTranslator } = require("next-intl");
const { transformSync } = require("next/dist/build/swc");
const resourceTest = require("./resource-library-helpers.cjs");
const { code } = transformSync(
  readFileSync(path.join(__dirname, "../components/ResourcesPanel.tsx"), "utf8"),
  {
    filename: "ResourcesPanel.tsx",
    jsc: {
      parser: { syntax: "typescript", tsx: true },
      target: "es2022",
      transform: { react: { runtime: "automatic" } },
    },
    module: { type: "commonjs" },
  },
);
function render(model, locale = "en", managementOnly = false) {
  model = { sources: [], ...model };
  const messages = require(`../messages/${locale}.json`);
  const imports = {
    "@/lib/holdings-publication": resourceTest.compile("../lib/holdings-publication.ts", {
      "./resource-library": resourceTest.contracts,
    }),
    "@/lib/holdings-facts": require("./resource-library-helpers.cjs").compile(
      "../lib/holdings-facts.ts",
    ),
    "./HoldingsEditor": { __esModule: true, default: () => null },
    "./HoldingsValuation": require("./resource-library-helpers.cjs").compile(
      "../components/HoldingsValuation.tsx",
      {
        react: React,
        "react/jsx-runtime": jsxRuntime,
        "next-intl": {
          useTranslations: (namespace) => createTranslator({ locale, messages, namespace }),
          useLocale: () => locale,
        },
        "./CurrencyPreferencesProvider": {
          useCurrencyPreferences: () => ({
            loaded: true,
            error: null,
            defaultPortfolioCurrency: "USD",
          }),
        },
        "./useHoldingsValuation": {
          useHoldingsValuation: (value) => ({
            facts: value.content
              ? require("./resource-library-helpers.cjs")
                  .compile("../lib/holdings-facts.ts")
                  .asFacts(value.content)
              : null,
            prices: null,
            valuation: null,
            options: ["USD"],
            currency: "USD",
            isDefault: true,
            busy: false,
            error: false,
            progress: null,
            select() {},
            reset() {},
            refresh() {},
          }),
        },
        "@/lib/holdings-facts": require("./resource-library-helpers.cjs").compile(
          "../lib/holdings-facts.ts",
        ),
        "@/lib/holdings-valuation": require("./resource-library-helpers.cjs").compile(
          "../lib/holdings-valuation.ts",
          { "../../../packages/encrypted-workspace/valuation/dist/index.mjs": {} },
        ),
        "./HoldingsValuation.module.css": { __esModule: true, default: {} },
      },
    ),
    "next/dynamic": { __esModule: true, default: () => imports["./HoldingsValuation"].default },
    react: React,
    "./PasskeyHelp": { PasskeyHelp: () => null },
    "./ResourceLibrary": {
      __esModule: true,
      default: ({ children }) =>
        typeof children === "function"
          ? children({ catalogue: { data: null, loading: false }, useForTask() {} })
          : children,
    },
    "./useDisplayNames": {
      useDisplayNames: () => ({
        name: () => null,
        pending: () => false,
        scope: "test",
        ready: true,
        enabled: true,
        clearError() {},
      }),
    },
    "./HoldingsSourceBar": require("./resource-library-helpers.cjs").compile(
      "../components/HoldingsSourceBar.tsx",
      {
        react: React,
        "react/jsx-runtime": jsxRuntime,
        "next-intl": {
          useTranslations: (namespace) => createTranslator({ locale, messages, namespace }),
          useLocale: () => locale,
        },
        "./useTasks": { useTasks: () => ({ items: [], taskNames: {} }) },
        "./ResourcesPanel.module.css": {
          __esModule: true,
          default: new Proxy({}, { get: (_, k) => k }),
        },
      },
    ),
    "react/jsx-runtime": jsxRuntime,
    "next-intl": {
      useLocale: () => locale,
      useTranslations: (namespace) => createTranslator({ locale, messages, namespace }),
      useLocale: () => locale,
    },
    "@/components/useHoldingsWorkspace": { useHoldingsWorkspace: () => model },
    "./ResourcesPanel.module.css": {
      __esModule: true,
      default: new Proxy({}, { get: (_object, name) => name }),
    },
  };
  const module = { exports: {} };
  vm.runInNewContext(code, {
    module,
    exports: module.exports,
    require: (name) => {
      if (["./WorkspaceFeedback", "./ReportDialog"].includes(name))
        return require("./workspace-feedback-helpers.cjs").component(name, imports);
      assert.ok(name in imports, name);
      return imports[name];
    },
  });
  return renderToStaticMarkup(
    managementOnly
      ? React.createElement(module.exports.SourceManagement, { model })
      : React.createElement(module.exports.default, { onOpenWatchlist: () => {} }),
  );
}
const base = {
  authenticated: false,
  configured: true,
  authStatus: "anonymous",
  phase: "checking",
  busy: null,
  preview: null,
  content: null,
  hasPending: false,
  error: "",
  errorRow: null,
  notice: "",
  signIn() {},
  create() {},
  unlock() {},
  lock() {},
  reload() {},
  readStored() {},
  importFile() {},
  save() {},
  selectAccounts() {},
  discardPreview() {},
};
const content = {
  state: "ready",
  coverage: { state: "unknown", issues: [] },
  sourceAsOf: null,
  fetchedAt: "2026-10-28T19:00:00Z",
  freshness: "unknown",
  data: {
    kind: "holdings",
    snapshotId: "snapshot_a",
    accounts: [
      {
        accountId: "account_a",
        displayName: "Synthetic · ••••4821",
        balances: [{ currency: "CAD", cashBalance: null, buyingPower: null }],
        positions: [
          {
            assetId: "asset_a",
            symbol: "SYNTH",
            name: '<img src=x onerror="private">',
            exchange: "XSYN",
            currency: "CAD",
            quantity: "9007199254740993.000000000001",
            marketValue: { currency: "CAD", amount: "9007199254740993.000000000001" },
          },
        ],
      },
    ],
    excludedAssets: [],
  },
};

test("guest sees collapsed export help without unsupported broker choices", () => {
  const html = render(base);
  assert.ok(
    html.includes(
      "https://help.wealthsimple.com/hc/en-ca/articles/35654428540571-Request-a-custom-statement",
    ),
  );
  for (const step of [
    "Profile",
    "Documents",
    "Generate document",
    "Holdings report (CSV)",
    "As of date",
    "Download CSV",
  ])
    assert.ok(html.includes(step));
  assert.ok(!html.includes("Robinhood"));
  assert.ok(!html.includes("Interactive Brokers"));
  assert.ok(html.includes("<details"));
  assert.ok(html.includes("Sign in with Google"));
  assert.ok(!html.includes('type="file"'));
  assert.ok(!html.includes("PRIVATE_SENTINEL"));
});

test("missing private origins show unavailable storage without fake success or import action", () => {
  const html = render({ ...base, authenticated: true, configured: false, phase: "unlocked" });
  assert.ok(html.includes("Holdings storage is not enabled"));
  assert.ok(!html.includes('type="file"'));
  assert.ok(!html.includes("Confirm, encrypt and save"));
  assert.ok(!html.includes("snapshot was saved"));
});

test("locked library does not render stale decrypted holdings even if a caller supplies them", () => {
  const html = render({ ...base, authenticated: true, phase: "locked", content });
  assert.ok(html.includes("Unlock with passkey"));
  assert.ok(!html.includes("9007199254740993"));
  assert.ok(!html.includes("onerror"));
});

test("a renewal-only session hides stale holdings and ordinary import or unlock actions", () => {
  for (const locale of ["en", "zh"]) {
    const html = render({ ...base, authenticated: true, phase: "renewal-only", content }, locale);
    assert.ok(html.includes(locale === "en" ? "Only key renewal is open" : "当前仅开放密钥续期"));
    assert.ok(!html.includes("9007199254740993"));
    assert.ok(!html.includes('type="file"'));
    assert.ok(!html.includes(locale === "en" ? "Unlock with passkey" : "使用通行密钥解锁"));
  }
});

test("unlocked private view escapes CSV text and retains all decimal precision", () => {
  const html = render({ ...base, authenticated: true, phase: "unlocked", content });
  assert.ok(html.includes("9,007,199,254,740,993.000000000001"));
  assert.ok(html.includes("&lt;img"));
  assert.ok(!html.includes("<img"));
  assert.ok(html.includes("Unknown"));
  assert.ok(html.includes("not a confirmed withdrawable balance or buying power"));
});

test("Chinese resources UI translates passkey errors and upload guide without a key-file workflow", () => {
  const html = render(
    { ...base, authenticated: true, phase: "locked", error: "passkey_unsupported" },
    "zh",
  );
  assert.ok(html.includes("通行密钥"));
  assert.ok(html.includes("不支持所需"));
  assert.ok(html.includes("不会改为上传明文"));
  assert.ok(html.includes("如何导出 Wealthsimple 持仓 CSV"));
  assert.ok(!html.includes('type="password"'));
  assert.ok(!html.includes('accept=".json"'));
});

const managedSource = {
  resourceRef: {
    kind: "holdings",
    sourceService: "portfolio",
    resourceId: "holdings_a",
    incarnation: "inc_a",
  },
  sourceEpoch: 2,
};
const managed = {
  ...base,
  authenticated: true,
  phase: "unlocked",
  canWriteState: true,
  sources: [managedSource],
  selectedSourceId: "holdings_a",
  newSource: false,
  sourceMetadata: {
    source: managedSource,
    authorityVersion: 3,
    revision: 1,
    snapshotId: "snapshot_a",
    snapshotSourceEpoch: 1,
    state: "active",
    pendingMutationId: null,
  },
};

test("unknown or unloaded saved holdings render checking or error, not an actionable empty importer", () => {
  for (const locale of ["en", "zh", "zh-Hant"]) {
    const labels = require(`../messages/${locale}.json`).resources;
    for (const sourceMetadata of [null, managed.sourceMetadata]) {
      const html = render({ ...managed, sourceMetadata, busy: null }, locale);
      assert.ok(!html.includes('type="file"'));
      assert.ok(
        !/<p class="note">Wealthsimple[\s\S]*?<\/p>/.test(html),
        "unknown contents do not guess a CSV source caption",
      );
      const view = interactiveWorkspace({ ...managed, sourceMetadata, busy: null }, locale);
      const loading = view.all(
        view.draw(),
        (node) => node.type?.name === "LoadingIndicator" && node.props.label === labels.loading,
      );
      assert.equal(loading.length, 1);
      assert.equal(
        loading[0].props.busy,
        true,
        "the existing delayed status indicator receives the real unresolved state",
      );
      view.close();
    }
    const failed = render(
      { ...managed, sourceMetadata: null, error: "service_unavailable" },
      locale,
    );
    assert.ok(failed.includes(labels.errors.service_unavailable));
    assert.ok(!failed.includes('type="file"'));
    const empty = render(
      {
        ...managed,
        sourceMetadata: {
          ...managed.sourceMetadata,
          snapshotId: null,
          revision: 0,
          snapshotSourceEpoch: null,
        },
      },
      locale,
    );
    assert.ok(
      empty.includes('type="file"'),
      "only a confirmed empty head exposes the empty importer",
    );
    const emptyView = interactiveWorkspace(
      {
        ...managed,
        sourceMetadata: {
          ...managed.sourceMetadata,
          snapshotId: null,
          revision: 0,
          snapshotSourceEpoch: null,
        },
      },
      locale,
    );
    assert.ok(
      emptyView
        .all(
          emptyView.draw(),
          (node) => node.type?.name === "LoadingIndicator" && node.props.label === labels.loading,
        )
        .every((node) => !node.props.busy),
    );
    emptyView.close();
  }
});

test("loaded source captions use actual manual or imported content and keep selection controls", () => {
  const manual = resourceTest.compile("../lib/holdings-facts.ts").asFacts(content);
  manual.data.importSnapshot = null;
  manual.data.editKind = "manual";
  for (const locale of ["en", "zh", "zh-Hant"]) {
    const messages = require(`../messages/${locale}.json`).resources;
    assert.ok(
      render({ ...managed, content: manual }, locale).includes(messages.editing.manualSource),
    );
    assert.match(render({ ...managed, content }, locale), /<p class="note">Wealthsimple/);
    assert.ok(render({ ...managed, content }, locale).includes(messages.lifecycle.settings));
    assert.ok(
      !render({ ...managed, sourceMetadata: null }, locale).includes(messages.lifecycle.settings),
    );
  }
});

function interactiveWorkspace(model, locale = "en") {
  const { hooks, jsx, all } = require("./resource-ui-harness.cjs"),
    ui = hooks(),
    Editor = () => null;
  const mod = resourceTest.compile("../components/ResourcesPanel.tsx", {
    react: ui.react,
    "react/jsx-runtime": { jsx, jsxs: jsx },
    "next-intl": {
      useTranslations: (namespace) =>
        createTranslator({ locale, messages: require(`../messages/${locale}.json`), namespace }),
    },
    "next/dynamic": { __esModule: true, default: () => () => null },
    "@/components/useHoldingsWorkspace": {},
    "@/lib/holdings-facts": resourceTest.compile("../lib/holdings-facts.ts"),
    "./HoldingsEditor": { __esModule: true, default: Editor },
    "./ResourceLibrary": { __esModule: true, default: () => null },
    "./PasskeyHelp": {},
    "./HoldingsSourceBar": {},
    "./useDisplayNames": { useDisplayNames: () => ({ scope: "names" }) },
    "./ResourcesPanel.module.css": { __esModule: true, default: {} },
  });
  return {
    draw: () =>
      ui.render(() => {
        const panel = mod.default({ workspace: model });
        const view = panel.type(panel.props);
        const library = all(view, (node) => typeof node.props?.children === "function")[0];
        const layout = library.props.children({ catalogue: { data: null, loading: false } });
        const workspace = all(layout, (node) => node.type?.name === "Workspace")[0];
        return workspace.type(workspace.props);
      }),
    all,
    Editor,
    close: ui.close,
  };
}

test("unloaded or failed heads cannot open an editing preview; confirmed empty and explicit new-source paths remain usable", () => {
  for (const patch of [
    { sourceMetadata: null },
    { sourceMetadata: managed.sourceMetadata },
    { sourceMetadata: null, error: "service_unavailable" },
    { sourceMetadata: { ...managed.sourceMetadata, snapshotId: null, revision: 0 }, empty: true },
    { newSource: true, sourceMetadata: null, empty: true },
  ]) {
    let imports = 0;
    const view = interactiveWorkspace({ ...managed, ...patch, importFile: () => imports++ });
    let tree = view.draw();
    const add = view.all(
      tree,
      (node) => node.type === "button" && node.props.children === "Add position",
    )[0];
    const inputs = view.all(tree, (node) => node.type === "input" && node.props.type === "file");
    assert.equal(add.props.disabled, !patch.empty);
    if (!add.props.disabled) add.props.onClick(); // Match native disabled-button event behavior.
    tree = view.draw();
    assert.equal(view.all(tree, (node) => node.type === view.Editor).length, patch.empty ? 1 : 0);
    assert.equal(inputs.length, patch.empty ? 1 : 0);
    if (inputs.length)
      inputs[0].props.onChange({ target: { files: [{ name: "synthetic.csv" }], value: "" } });
    assert.equal(imports, patch.empty ? 1 : 0);
    view.close();
  }
});

test("source controls explain actual access effects without exposing internal source IDs", () => {
  for (const locale of ["en", "zh"]) {
    const html = render(managed, locale, true);
    assert.ok(html.includes(locale === "en" ? "Invalidate previous access" : "使旧授权失效"));
    assert.ok(html.includes(locale === "en" ? "previous scope" : "历史持仓"));
    assert.ok(!html.includes("inc_a"));
    assert.ok(!html.includes("sourceEpoch"));
  }
});

test("delete review states logical retention and copied-content limits in both languages", () => {
  for (const locale of ["en", "zh"]) {
    const html = render(
      {
        ...managed,
        sourceReview: { action: "delete", source: managedSource, authorityVersion: 3 },
      },
      locale,
      true,
    );
    assert.ok(html.includes("fieldset"));
    assert.ok(html.includes(locale === "en" ? "physical erasure" : "物理清除"));
    assert.ok(html.includes(locale === "en" ? "cannot be recalled" : "无法收回"));
    assert.ok(html.includes(locale === "en" ? "Cancel and keep" : "取消，保持"));
  }
});

test("pending or acknowledged deletion never renders stale supplied holdings plaintext", () => {
  for (const state of ["revoking", "deleted"]) {
    const html = render({
      ...managed,
      content,
      sourceMetadata: { ...managed.sourceMetadata, state },
      sourceMutation:
        state === "revoking"
          ? {
              action: "delete",
              state: "pending",
              operationId: "synthetic_delete_operation_0001",
              sourceEpoch: 2,
            }
          : null,
    });
    assert.ok(!html.includes("9007199254740993"));
    assert.ok(!html.includes("&lt;img"));
    assert.ok(!html.includes("snapshot was saved"));
  }
});

test("disconnected data retains readable owner history while the upload control is disabled", () => {
  const html = render({
    ...managed,
    content,
    sourceMetadata: { ...managed.sourceMetadata, state: "disconnected" },
  });
  assert.ok(
    render(
      { ...managed, sourceMetadata: { ...managed.sourceMetadata, state: "disconnected" } },
      "en",
      true,
    ).includes("Existing holdings remain readable"),
  );
  assert.ok(html.includes("9,007,199,254,740,993"));
  assert.ok(!html.includes('type="file"'));
  assert.ok(html.includes("New holdings source"));
});

test("locked and renewal-only phases hide source management and all prior private facts", () => {
  for (const phase of ["locked", "renewal-only"]) {
    const html = render({
      ...managed,
      phase,
      content,
      sourceReview: { action: "delete" },
      sourceMutation: { action: "delete" },
    });
    assert.ok(!html.includes("Manage holdings data"));
    assert.ok(!html.includes("9,007,199,254,740,993"));
    assert.ok(!html.includes("Confirm this change"));
  }
});

test("uncertain creation offers original-result recovery without declaring a completed upload", () => {
  const html = render({ ...managed, sourceCreationId: "source_synthetic_pending" });
  const recovery = render({ ...managed, sourceCreationId: "source_synthetic_pending" }, "en", true);
  assert.ok(recovery.includes("Check original creation"));
  assert.ok(recovery.includes("without creating a duplicate"));
  assert.ok(recovery.includes("Only a request that can no longer be submitted"));
  assert.ok(!html.includes("snapshot was saved"));
  assert.ok(
    !html.includes('type="file"'),
    "unread existing holdings stay hidden behind creation recovery",
  );
  assert.match(html, /<button[^>]*disabled[^>]*>Add position<\/button>/);
});
