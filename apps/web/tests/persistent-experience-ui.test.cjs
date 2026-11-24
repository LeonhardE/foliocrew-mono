const assert = require("node:assert/strict"),
  test = require("node:test"),
  React = require("react");
const { renderToStaticMarkup } = require("react-dom/server"),
  { createTranslator } = require("next-intl");
const { compile } = require("./resource-library-helpers.cjs");
const { all, hooks, jsx: testJsx } = require("./resource-ui-harness.cjs");
const jsx = require("react/jsx-runtime");
const connectionContracts = compile("../lib/agent-connections.ts");
function render(locale, unlocked, plan, credential = null, duration = null, state = {}) {
  const ui = state.interact ? hooks() : null;
  const imports = {
    react: ui?.react ?? React,
    "@/lib/provider-groups": compile("../lib/provider-groups.ts"),
    "@/lib/agent-connections": connectionContracts,
    "./ProviderMark": {
      ProviderMark: ({ provider }) =>
        React.createElement("span", { "data-provider": provider }, provider),
    },
    "./ReportDialog": { ReportDialog: () => null },
    "./WorkspaceFeedback": { LoadingIndicator: () => null, InlineError: () => null },
    "react/jsx-runtime": ui ? { jsx: testJsx, jsxs: testJsx } : jsx,
    "next-intl": {
      useLocale: () => locale,
      useTranslations: (namespace) =>
        createTranslator({
          locale,
          messages: require("../messages/" + locale + ".json"),
          namespace,
        }),
    },
    "./AuthProvider": {
      useAuth: () =>
        state.auth ?? {
          requestNativeAccount: async () => {
            throw Error("render cannot authorize");
          },
        },
    },
    "@/lib/native-owner-bridge": state.native ?? {},
    "@/lib/agent-authorization": { agentAuthorizationHandoff: () => state.pairing ?? null },
    "@/lib/persistent-experience-controller": {
      DEFAULT_CONNECTION_SECONDS: 7776000,
      TEMPORARY_CONNECTION_SECONDS: 900,
    },
    "./AgentsPanel.module.css": new Proxy({}, { get: (_t, k) => String(k) }),
  };
  const components = compile("../components/PersistentAgentsPanel.tsx", imports, {
    Intl,
    navigator: state.navigator,
    window: state.window,
    setTimeout: () => 0,
    clearTimeout: () => {},
    Date:
      state.now === undefined
        ? Date
        : class extends Date {
            static now() {
              return state.now * 1000;
            }
          },
  });
  if (duration)
    return renderToStaticMarkup(
      React.createElement(components.AgentConnectionDuration, { ...duration, onChange() {} }),
    );
  const Panel = components.PersistentAgentsPanel;
  const workspace = {
    authenticated: true,
    owner: "owner_A",
    vaultGeneration: 1,
    phase: unlocked ? "unlocked" : "locked",
    canWriteState: unlocked,
    busy: false,
    unlock() {
      throw Error("render cannot unlock");
    },
    ...state.workspace,
  };
  const model = {
    owner: "owner_A",
    unlocked,
    busy: false,
    loading: false,
    loaded: true,
    displayState: "ready",
    loadError: false,
    error: "",
    enabled: true,
    reload: async () => true,
    providerStates: {},
    views: [
      {
        connection: {
          connectionId: "connection_A",
          clientId: "muse_A",
          provider: "muse",
          status: "active",
          accountState: "connected",
          linkedAt: 1000,
        },
        identity: {},
        credential,
        policy: { permissions: [{ status: "active" }] },
        pending: false,
        tasks: [
          {
            taskId: "task_A",
            title: "PRIVATE_TASK_CANARY",
            content: {
              deliveryExpectation: {
                cadence: "daily",
                localTime: "09:00",
                timeZone: "America/Toronto",
              },
            },
            plan,
          },
        ],
      },
    ],
    ...state.model,
    ...(state.slots
      ? {
          loaded: state.slots.loaded ?? true,
          loading: state.slots.loading ?? false,
          loadError: state.slots.error ?? false,
          providerStates: state.slots.states ?? {},
        }
      : {}),
  };
  const props = {
    workspace,
    model,
    origin: "https://agent-hub-api-123456789.northamerica-northeast2.run.app",
    brandOrigin: state.brandOrigin,
    active: state.active ?? !ui,
  };
  return ui
    ? state.interact(() => ui.render(() => Panel(props)))
    : renderToStaticMarkup(React.createElement(Panel, props));
}
test("Agent management offers Passkey setup before unlock for a new account", () => {
  let created = false;
  render("en", false, null, null, null, {
    workspace: {
      phase: "needs-vault",
      vaultConfigured: true,
      create() {
        created = true;
      },
    },
    interact(view) {
      const tree = view();
      const button = all(
        tree,
        (node) => node.type === "button" && node.props.children === "Set up Passkey",
      )[0];
      assert.ok(button);
      assert.equal(button.props.disabled, false);
      assert.equal(
        all(tree, (node) => node.type === "button" && node.props.children === "Unlock").length,
        0,
      );
      button.props.onClick();
    },
  });
  assert.equal(created, true);
});

test("account-only confirmation returns to the original authorization with a locked vault", async () => {
  const bridge = { close() {} };
  const approvals = [];
  let returned = false;
  await render("en", false, null, null, null, {
    active: true,
    workspace: { vault: { vaultId: "vault_A" }, canWriteState: false },
    window: {
      location: { hash: "", search: "?native_request=synthetic" },
      history: { replaceState() {} },
      close() {
        returned = true;
      },
    },
    native: {
      nativeHandoff: () => ({ requestId: "synthetic" }),
      async connectNativeOwnerBridge() {
        return bridge;
      },
    },
    auth: {
      async requestNativeAccount(peer, operation, input, owner) {
        assert.equal(peer, bridge);
        assert.equal(owner, "owner_A");
        if (operation === "pending") return { provider: "muse" };
        approvals.push(input.vaultId);
        return { state: "connected", authority: "account_link_only" };
      },
    },
    async interact(view) {
      const button = (label) =>
        all(view(), (node) => node.type === "button" && node.props.children === label)[0];
      view();
      await Promise.resolve();
      view();
      await Promise.resolve();
      const confirm = button("Confirm account");
      assert.equal(confirm.props.disabled, false);
      assert.equal(button("Unlock"), undefined);
      confirm.props.onClick();
      await new Promise(setImmediate);
      assert.deepEqual(approvals, ["vault_A"]);
      button("Back to authorization window").props.onClick();
      assert.equal(returned, true);
    },
  });
});

test("a newly linked account shows its next step on the current provider card without a history list", () => {
  const now = 1_800_000_000;
  const current = {
    connection: {
      provider: "muse",
      connectionId: "current",
      status: "active",
      accountState: "connected",
      linkedAt: now - 2000,
    },
    credential: { status: "expired", expiresAt: now - 600, reference: { connectionId: "current" } },
    tasks: [],
  };
  for (const [accountState, secondsAgo, badge, action] of [
    ["connecting", 1, "Waiting for account link", null],
    ["connecting", 300, "Account link timed out", "Restart account link"],
    ["connected", 1, "Waiting for final approval", "Continue connection"],
  ]) {
    const replacement = {
      connection: {
        provider: "muse",
        connectionId: "newer",
        status: "active",
        accountState,
        linkedAt: now - secondsAgo,
      },
      identity: null,
      credential: null,
      tasks: [],
    };
    const html = render("en", true, null, null, null, {
      now,
      model: {
        views: [current, replacement],
        providerStates: { muse: { slot: { currentCredential: current.credential.reference } } },
      },
    });
    assert.ok(html.includes(badge));
    if (action) assert.ok(html.includes(action));
    else assert.doesNotMatch(html, /Restart account link|Authorize again/);
    assert.doesNotMatch(html, /Connection history|Previous connection|Authorization needed/);
    assert.equal(html.split("Unlink account").length - 1, 1);
  }
});

test("an unlocked workspace opens the pairing review without approving it", async () => {
  const pairing = { setupIntentId: "synthetic_intent" };
  let inspected = 0;
  await render("en", true, null, null, null, {
    active: true,
    pairing,
    native: { nativeHandoff: () => null },
    window: {
      location: { hash: "#synthetic", search: "" },
      history: { replaceState() {} },
    },
    model: {
      enabled: false,
      async execute(request) {
        return request({
          inspectAuthorization(value) {
            assert.equal(value, pairing);
            inspected++;
            return { connection: { provider: "muse" }, tasks: [] };
          },
          authorize() {
            throw Error("the Owner has not approved");
          },
        });
      },
    },
    async interact(view) {
      view();
      await new Promise(setImmediate);
      const buttons = all(view(), (node) => node.type === "button").map(
        (node) => node.props.children,
      );
      assert.ok(buttons.includes("Authorize and connect"));
      assert.equal(inspected, 1);
    },
  });
});

test("successful approval offers a copyable final step in every workbench language", async () => {
  const cases = [
    [
      "en",
      "Authorize and connect",
      "Authorization saved",
      "Copy message",
      "Copied",
      /finish setting up the same connection/,
    ],
    ["zh", "授权并连接", "授权已保存", "复制消息", "已复制", /请完成刚才的连接/],
    ["zh-Hant", "授權並連線", "授權已儲存", "複製訊息", "已複製", /請完成剛才的連線/],
  ];
  for (const [locale, approve, saved, copy, copied, sameConnection] of cases) {
    const writes = [];
    const button = (tree, label) =>
      all(tree, (node) => node.type === "button" && node.props.children === label)[0];
    await render(locale, true, null, null, null, {
      active: true,
      pairing: { setupIntentId: "synthetic_intent" },
      native: { nativeHandoff: () => null },
      window: {
        location: { hash: "#synthetic", search: "" },
        history: { replaceState() {} },
      },
      navigator: {
        clipboard: {
          async writeText(value) {
            writes.push(value);
          },
        },
      },
      model: {
        async execute(request) {
          return request({
            inspectAuthorization: () => ({ connection: { provider: "muse" }, tasks: [] }),
            authorize: () => ({ connected: true }),
          });
        },
      },
      async interact(view) {
        assert.equal(button(view(), copy), undefined);
        await new Promise(setImmediate);
        button(view(), approve).props.onClick();
        await new Promise(setImmediate);
        const finished = view();
        assert.ok(
          all(finished, (node) => node.type === "h2" && node.props.children === saved).length,
        );
        const [field] = all(finished, (node) => node.type === "textarea");
        assert.equal(field.props.readOnly, true);
        assert.match(field.props.value, sameConnection);
        const [instructions] = all(
          finished,
          (node) => node.props.id === field.props["aria-describedby"],
        );
        assert.match(instructions.props.children, /Muse/);
        await button(finished, copy).props.onClick();
        assert.deepEqual(writes, [field.props.value]);
        assert.ok(button(view(), copied));
      },
    });
  }
});

test("Agent connection messages copy the exact localized text and the branded address", async () => {
  const brand = connectionContracts.BRANDED_AGENT_ORIGIN;
  const endpoint = brand + "/mcp/v3";
  const writes = [];
  const button = (tree, label) =>
    all(tree, (node) => node.type === "button" && node.props.children === label)[0];
  const message = (tree) => all(tree, (node) => node.type === "textarea")[0].props.value;
  const addressFromMessage = (value) =>
    value.split("\n").find((line) => line.startsWith("https://"));
  await render("zh", true, null, null, null, {
    brandOrigin: brand,
    model: { views: [] },
    navigator: {
      clipboard: {
        async writeText(value) {
          writes.push(value);
        },
      },
    },
    async interact(view) {
      button(view(), "连接 Muse").props.onClick();
      const muse = message(view());
      assert.match(muse, /^请帮我添加/);
      assert.equal(addressFromMessage(muse), endpoint);
      assert.match(muse, /foliocrew-muse-prod/);
      await button(view(), "复制消息").props.onClick();
      assert.deepEqual(writes, [muse]);
      assert.ok(button(view(), "已复制"));

      button(view(), "连接 ChatGPT").props.onClick();
      const chatgpt = message(view());
      assert.match(chatgpt, /^请帮我在 ChatGPT/);
      assert.equal(addressFromMessage(chatgpt), endpoint);
      assert.doesNotMatch(chatgpt, /foliocrew-muse-prod|val010/);
      assert.match(chatgpt, /打开原来的连接并重新授权/);
      assert.match(chatgpt, /联系 Foliocrew 管理员获取已登记的 ChatGPT 专用 Client ID/);
      await button(view(), "复制消息").props.onClick();
      assert.deepEqual(writes, [muse, chatgpt]);
    },
  });
  render("en", true, null, null, null, {
    model: { views: [] },
    interact(view) {
      button(view(), "Connect Muse").props.onClick();
      const guide = message(view());
      assert.match(guide, /^Help me add/);
      assert.equal(
        addressFromMessage(guide),
        "https://agent-hub-api-123456789.northamerica-northeast2.run.app/mcp/v3",
      );
      assert.doesNotMatch(guide, /Client ID/);
    },
  });
});
test("connection management links private tasks back to the task center and conceals them while locked", () => {
  for (const locale of ["zh", "en"]) {
    const open = render(locale, true, { reported: null, observed: { receivedAt: 1001 } });
    assert.match(open, /PRIVATE_TASK_CANARY/);
    assert.match(open, /href="\/tasks#task\/task_A"/);
    assert.doesNotMatch(open, /09:00|America\/Toronto|Waiting for Agent confirmation|已收到报告/);
    const locked = render(locale, false, null);
    assert.doesNotMatch(locked, /PRIVATE_TASK_CANARY/);
    assert.match(locked, locale === "zh" ? /解锁/ : /Unlock/);
    assert.match(open, /Claude/);
    assert.match(open, /Gemini/);
  }
});

test("connection UI offers ordinary reauthorization and expiry notice without exposing credential internals", () => {
  for (const locale of ["zh", "en"]) {
    const out = render(locale, true, null, {
      status: "expiring",
      expiresAt: Date.now() / 1000 + 86400,
      privateKey: "PRIVATE_KEY_CANARY",
      bindingFingerprint: "BINDING_CANARY",
      generation: 9,
    });
    assert.match(out, locale === "zh" ? /即将到期/ : /Expires soon/);
    assert.match(out, locale === "zh" ? /重新授权/ : /Authorize again/);
    assert.match(out, /Muse/);
    assert.match(out, /ChatGPT/);
    assert.doesNotMatch(
      out,
      /PRIVATE_KEY_CANARY|BINDING_CANARY|fingerprint|certificate|恢复码|恢复文件|recovery code|recovery file|JSON/,
    );
  }
});

test("connection duration keeps ninety days selected by default and freezes pending originals", () => {
  for (const locale of ["zh", "en"]) {
    const normal = render(locale, true, null, null, {
      seconds: 7776000,
      pending: false,
      busy: false,
    });
    assert.match(normal, /<option value="7776000" selected=""/);
    assert.equal((normal.match(/<option\b/g) ?? []).length, 2);
    assert.match(normal, locale === "zh" ? /15 分钟（临时）/ : /15 minutes \(temporary\)/);
    const pending = render(locale, true, null, null, { seconds: 900, pending: true, busy: false });
    assert.match(pending, /<select[^>]*disabled=""/);
    assert.match(pending, /<option value="900" selected=""/);
    assert.match(pending, locale === "zh" ? /时长已固定/ : /duration is fixed/);
    assert.doesNotMatch(
      normal + pending,
      /fingerprint|certificate|恢复码|恢复文件|recovery code|JSON/,
    );
  }
});

test("slow or failed connection reads never render an invented disconnection or enable reconnect", () => {
  for (const locale of ["en", "zh"]) {
    for (const state of [
      { model: { loaded: false, loading: true, views: [] } },
      { slots: { loaded: false, loading: true } },
      {
        model: {
          loaded: false,
          loading: false,
          loadError: true,
          error: "request_failed",
          views: [],
        },
      },
      { slots: { loaded: false, error: true } },
    ]) {
      const out = render(locale, true, null, null, null, state);
      assert.doesNotMatch(
        out,
        /Not connected|未连接|Authorization needed|需要重新授权|PRIVATE_TASK_CANARY/,
      );
      assert.match(
        out,
        state.model?.loadError || state.slots?.error
          ? /Status unavailable|状态暂不可用/
          : /Loading connections|正在加载连接/,
      );
      const cards = out.match(/<article[^>]*>[\s\S]*?<\/article>/g).slice(0, 2);
      const buttons = cards.map((card) => [card.match(/<button[^>]*>/)[0]]);
      assert.equal(buttons.length, 2);
      assert.ok(buttons.every(([tag]) => tag.includes('disabled=""')));
    }
    const empty = render(locale, true, null, null, null, { model: { views: [] } });
    assert.equal((empty.match(/Not connected|未连接/g) ?? []).length, 2);
    assert.ok(
      empty
        .match(/<article[^>]*>[\s\S]*?<\/article>/g)
        .slice(0, 2)
        .every((card) => !card.match(/<button[^>]*>/)[0].includes("disabled")),
    );
  }
});

test("revoked connections render the same empty setup cards for Muse and ChatGPT", () => {
  const views = ["muse", "chatgpt"].map((provider) => ({
    connection: { provider, status: "revoked", connectionId: provider + "_old" },
    credential: { status: "expired", expiresAt: 1 },
    tasks: [{ title: "PRIVATE_TASK_CANARY" }],
  }));
  const providerStates = {
    chatgpt: {
      slot: { currentCredential: { connectionId: "chatgpt_old" } },
      legacyBlockers: ["chatgpt_old"],
    },
  };
  for (const locale of ["en", "zh", "zh-Hant"]) {
    const state = { model: { views, providerStates } };
    assert.equal(
      render(locale, true, null, null, null, state),
      render(locale, true, null, null, null, { model: { views: [] } }),
    );
  }
});

test("refreshing keeps the last loaded connection visible and adds a busy indicator", () => {
  for (const locale of ["en", "zh"]) {
    const out = render(
      locale,
      true,
      null,
      {
        status: "active",
        expiresAt: Date.now() / 1000 + 7776000,
      },
      null,
      { model: { loading: true, busy: true } },
    );
    const muse = out.match(/<article[^>]*>[\s\S]*?<\/article>/)[0];
    assert.match(muse, /Connected|已连接/);
    assert.doesNotMatch(muse, /Not connected|未连接/);
    assert.match(muse, /aria-busy="true"/);
    assert.match(muse, /data-checking="true"/);
    assert.match(muse, /<button disabled="">(?:Revoke access|取消授权)/);
  }
});

test("background summary refresh preserves actions on the last verified connection", () => {
  const out = render(
    "en",
    true,
    null,
    { status: "active", expiresAt: Date.now() / 1000 + 7776000 },
    null,
    { model: { loading: true, busy: false } },
  );
  const muse = out.match(/<article[^>]*>[\s\S]*?<\/article>/)[0];
  assert.match(muse, /aria-busy="true"/);
  assert.match(muse, /<button>Revoke access/);
  assert.doesNotMatch(muse, /Authorize again|Continue authorization/);
});

test("Agent readiness reflects the complete verified display and never treats retained errors or stale data as ready", () => {
  const state = (options = {}, unlocked = true) => {
    const html = render("en", unlocked, null, null, null, options);
    return html.slice(0, html.indexOf(">") + 1);
  };
  assert.match(state(), /data-load-scope="agent-connections" data-load-state="ready"/);
  for (const model of [
    { loaded: false, loading: true, displayState: "loading" },
    { loaded: true, loading: true, displayState: "loading" },
    { loaded: true, loading: false, displayState: "loading" },
    { busy: true },
  ])
    assert.match(state({ model }), /data-load-state="loading"/);
  assert.match(
    state({ model: { loaded: true, loadError: true, displayState: "error" } }),
    /data-load-state="error"/,
  );
  assert.match(state({}, false), /data-load-state="locked"/);
  assert.match(state({ workspace: { owner: "owner_B" } }), /data-load-state="locked"/);
  assert.doesNotMatch(state(), /connection_A|owner_A|PRIVATE/);
});

test("expiry changes at the exact credential deadline and account unlinking follows the independent account status", () => {
  const now = 1_800_000_000;
  for (const [locale, expired, valid, unlink] of [
    ["en", "Credential expired on", "Valid until", "Unlink account"],
    ["zh", "执行凭证已于", "有效至", "解除账号关联"],
    ["zh-Hant", "執行憑證已於", "有效至", "解除帳號連結"],
  ]) {
    for (const provider of ["muse", "chatgpt"]) {
      function row(id, time, linked = true) {
        return {
          connection: {
            connectionId: id,
            status: linked ? "active" : "revoked",
            accountState: linked ? "relogin_required" : "revoked",
            provider,
          },
          credential: { status: "active", expiresAt: time, reference: { connectionId: id } },
          pending: false,
          tasks: [],
        };
      }
      const current = row("current", now);
      const previous = row("previous", now - 86400);
      const removed = row("removed", now - 86400, false);
      const model = {
        views: [current, previous, removed],
        providerStates: {
          [provider]: { slot: { currentCredential: current.credential.reference } },
        },
      };
      const at = (clock, unlocked = true) =>
        render(locale, unlocked, null, null, null, { now: clock, model });
      const earlier = at(now - 1);
      assert.ok(earlier.includes(valid));
      assert.equal(earlier.split(expired).length - 1, 0);
      for (const clock of [now, now + 1]) {
        const out = at(clock);
        assert.equal(out.split(expired).length - 1, 1);
        assert.equal(out.split(unlink).length - 1, 1);
        assert.ok(!out.includes(valid));
      }
      const locked = at(now, false);
      assert.ok(!locked.includes(expired));
      assert.ok(!locked.includes(unlink));
    }
  }
});
