(() => {
  "use strict";

  const messages = {
    en: {
      workspace: "Task center",
      close: "Close task demo",
      title: "Cedar holding review",
      flat: "Other holdings unchanged",
      progress: "Task progress",
      movement: "Holding move",
      questions: "Questions",
      working: "Research",
      complete: "Reports",
      value: "Cedar holding value",
      direction: "Down",
      position: "Same share count, lower quote",
      context: "Holding value fell",
      previous: "Earlier snapshot",
      latest: "Latest snapshot",
      why: "Why?",
      next: "Now What?",
      dispatch: "ChatGPT and Muse get the same questions and data.",
      single: "Both questions go to {name}.",
      research: "Working independently",
      returned: "Reports for this task",
      counts: ["0 reports", "1 report", "2 reports"],
      waiting: "Reading the holding snapshot",
      filed: "Report filed",
      reason: "Why",
      check: "Next check",
      chatgptReason:
        "The share count stayed the same. A lower quote brought the holding’s value down.",
      chatgptCheck: "Verify the quote times. The snapshots don’t explain why the price fell.",
      museReason: "No dated event in the shared sources explains the drop.",
      museCheck: "Compare Cedar’s announcements and sector returns over the same dates.",
      settings: "Task resources and access",
      sources: "From Resources",
      draft: "Cedar holding snapshot",
      youtube: "YouTube follows",
      channel: "Cedar Research Notes · channel name only",
      noSources: "No resources shared",
      recipients: "Assigned agents",
      share: "Share the holding snapshot",
      optional: "Share followed channels",
      denied: "Share the holding snapshot to run this task.",
      unassigned: "Assign an agent to run this task.",
      pause: "Pause",
      resume: "Resume",
      simulation: "Local demo · fictional data",
    },
    "zh-Hans": {
      workspace: "任务中心",
      close: "关闭任务演示",
      title: "Cedar 持仓复盘",
      flat: "其他持仓持平",
      progress: "任务进度",
      movement: "持仓变动",
      questions: "提问",
      working: "研究",
      complete: "报告",
      value: "Cedar 持仓市值",
      direction: "回落",
      position: "股数未变，报价走低",
      context: "持仓市值回落",
      previous: "前次快照",
      latest: "本次快照",
      why: "为什么会跌？",
      next: "接下来怎么办？",
      dispatch: "把同样的问题和资料交给 ChatGPT 和 Muse。",
      single: "这两个问题都交给 {name}。",
      research: "Agent 正在独立研究",
      returned: "本次任务的报告",
      counts: ["0 份报告", "1 份报告", "2 份报告"],
      waiting: "正在查看持仓快照",
      filed: "报告已提交",
      reason: "原因",
      check: "下一步",
      chatgptReason: "持股数量没变，报价下跌让市值随之回落。",
      chatgptCheck: "先核对报价时间。价格为何下跌，还需要快照以外的证据。",
      museReason: "共享资料里没有能解释下跌的同期事件。",
      museCheck: "查一查 Cedar 的公司公告，再对照同期行业表现。",
      settings: "任务资料与权限",
      sources: "来自资源库",
      draft: "Cedar 持仓快照",
      youtube: "YouTube 关注",
      channel: "Cedar Research Notes · 仅频道名称",
      noSources: "尚未共享资料",
      recipients: "执行任务的 Agent",
      share: "共享持仓快照",
      optional: "共享关注的频道",
      denied: "请先共享持仓快照。",
      unassigned: "请选择执行任务的 Agent。",
      pause: "暂停",
      resume: "继续",
      simulation: "本地演示 · 虚构数据",
    },
    "zh-Hant": {
      workspace: "任務中心",
      close: "關閉任務示範",
      title: "Cedar 持倉回顧",
      flat: "其他持倉持平",
      progress: "任務進度",
      movement: "持倉變動",
      questions: "提問",
      working: "研究",
      complete: "報告",
      value: "Cedar 持倉市值",
      direction: "回落",
      position: "股數未變，報價走低",
      context: "持倉市值回落",
      previous: "前次快照",
      latest: "本次快照",
      why: "為什麼會跌？",
      next: "接下來怎麼辦？",
      dispatch: "把相同的問題和資料交給 ChatGPT 與 Muse。",
      single: "這兩個問題都交給 {name}。",
      research: "Agent 正在獨立研究",
      returned: "這項任務的報告",
      counts: ["0 份報告", "1 份報告", "2 份報告"],
      waiting: "正在查看持倉快照",
      filed: "報告已提交",
      reason: "原因",
      check: "下一步",
      chatgptReason: "持股數量未變，報價下滑讓持倉市值跟著回落。",
      chatgptCheck: "先核對報價時間。要找出下跌原因，還需要快照以外的證據。",
      museReason: "共享資料裡沒有能解釋跌勢的同期事件。",
      museCheck: "查閱 Cedar 的公司公告，再對照同期產業表現。",
      settings: "任務資料與權限",
      sources: "來自資源庫",
      draft: "Cedar 持倉快照",
      youtube: "YouTube 關注",
      channel: "Cedar Research Notes · 僅頻道名稱",
      noSources: "尚未共享資料",
      recipients: "執行任務的 Agent",
      share: "共享持倉快照",
      optional: "共享關注的頻道",
      denied: "請先共享持倉快照。",
      unassigned: "請選擇執行任務的 Agent。",
      pause: "暫停",
      resume: "繼續",
      simulation: "本機示範 · 虛構資料",
    },
  };
  const authors = { chatgpt: "ChatGPT", muse: "Muse" };
  const phases = ["movement", "questions", "working", "partial", "complete"];
  const durations = [3000, 3500, 2500, 3000, 8000];
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  const dialog = document.createElement("dialog");
  dialog.id = "fc-sample";
  dialog.setAttribute("aria-labelledby", "fc-sample-title");
  dialog.setAttribute("aria-describedby", "fc-sample-hint");

  function authorLane(key, name) {
    return `<section class="sample-lane" data-agent="${key}" aria-labelledby="fc-author-${key}">
      <header><span class="sample-author-dot" aria-hidden="true"></span>
        <h4 id="fc-author-${key}">${name}</h4><span class="sample-sr" data-agent-state></span></header>
      <div class="sample-reading" data-agent-pending><i aria-hidden="true"></i><span data-word="waiting"></span></div>
      <article data-sample-report="${key}" aria-labelledby="fc-author-${key}" hidden>
        <p><b data-word="reason"></b> <span data-word="${key}Reason"></span></p>
        <p><b data-word="check"></b> <span data-word="${key}Check"></span></p>
      </article>
    </section>`;
  }

  dialog.innerHTML = `<div class="sample-frame">
    <header class="sample-appbar">
      <div class="sample-crumb"><b>Foliocrew</b><span aria-hidden="true">/</span><span data-word="workspace"></span></div>
      <button type="button" data-sample-close data-label="close"><span aria-hidden="true"></span></button>
    </header>
    <div class="sample-scroll">
      <div class="sample-task-head"><h2 id="fc-sample-title" tabindex="-1" data-word="title"></h2>
        <span data-sample-context hidden><b aria-hidden="true">↘</b> <span data-word="context"></span></span></div>
      <ol class="sample-track" data-label="progress">
        ${["movement", "questions", "working", "complete"].map((name) => `<li data-track="${name}"><i></i><span data-word="${name}"></span></li>`).join("")}
      </ol>
      <div class="sample-stage">
        <section class="sample-movement" data-sample-movement aria-labelledby="fc-move">
          <div class="sample-reading-move"><h3 id="fc-move" data-word="value"></h3><strong data-word="direction"></strong>
            <div class="sample-observations"><p data-word="position"></p><p data-word="flat"></p></div>
          </div>
          <div class="sample-plot">
            <div class="sample-chart" aria-hidden="true">
              <svg viewBox="0 0 400 120" preserveAspectRatio="none"><defs><linearGradient id="fc-chart-fill" x1="0" x2="0" y1="0" y2="1"><stop stop-color="currentColor" stop-opacity=".25"/><stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs>
                <path class="sample-guide" d="M0 14H400 M0 100H400"/><path class="sample-area" d="M16 14L383 100V120H16Z"/>
                <path class="sample-slope" pathLength="1" d="M16 14L383 100"/><ellipse class="sample-dot start" cx="16" cy="14" rx="4.8" ry="4.8"/><ellipse class="sample-dot end" cx="383" cy="100" rx="4.8" ry="4.8"/></svg>
            </div>
            <div class="sample-snapshots"><span data-word="previous"></span><span data-word="latest"></span></div>
          </div>
        </section>
        <section class="sample-questions" data-sample-questions data-label="questions" hidden>
          <p class="sample-prompt"><span aria-hidden="true">↳</span><b data-word="why"></b></p>
          <p class="sample-prompt"><span aria-hidden="true">↳</span><b data-word="next"></b></p>
          <p class="sample-assignment" data-assignment></p>
        </section>
        <section class="sample-results" data-sample-results aria-labelledby="fc-results-title" hidden>
          <div class="sample-results-title"><h3 id="fc-results-title"></h3><span data-sample-count></span></div>
          <div class="sample-lanes">${Object.entries(authors)
            .map(([key, name]) => authorLane(key, name))
            .join("")}</div>
        </section>
        <p class="sample-fallback" data-sample-empty hidden></p>
      </div>
      <details data-sample-access><summary data-word="settings"></summary>
        <div class="sample-access-panel"><section data-sample-bundle><h3 data-word="sources"></h3>
          <p data-source-item="shared"><b data-word="draft"></b><span data-sample-brief><span data-word="context"></span> · <span data-word="position"></span> · <span data-word="flat"></span></span></p>
          <p data-source-item="youtube"><b data-word="youtube"></b><span data-word="channel"></span></p><p data-no-sources data-word="noSources" hidden></p>
        </section>
        <div class="sample-options">
          <label><input type="checkbox" name="shared" checked><span data-word="share"></span></label>
          <label><input type="checkbox" name="youtube" checked><span data-word="optional"></span></label>
          <fieldset><legend data-word="recipients"></legend>
            <label><input type="checkbox" name="chatgpt" checked>ChatGPT</label><label><input type="checkbox" name="muse" checked>Muse</label>
          </fieldset></div></div>
      </details>
    </div>
    <footer class="sample-footer"><p id="fc-sample-hint" data-word="simulation"></p>
      <button type="button" data-sample-pause></button>
    </footer>
    <p class="sample-sr" aria-live="polite" aria-atomic="true" data-run-status></p>
  </div>`;
  document.body.append(dialog);

  const get = (selector) => dialog.querySelector(selector);
  const scope = () =>
    Object.fromEntries(
      ["shared", "youtube", ...Object.keys(authors)].map((key) => [
        key,
        get(`input[name="${key}"]`).checked,
      ]),
    );
  let language = "en";
  let opener = null;
  let stage = 0;
  let timer = null;
  let started = 0;
  let remaining = durations[0];
  let paused = false;

  function render() {
    const words = messages[language];
    const allowed = scope();
    const assigned = Object.keys(authors).filter((key) => allowed.shared && allowed[key]);
    const phase = assigned.length ? phases[stage] : "blocked";
    dialog.dataset.phase = phase;
    dialog.dataset.paused = String(paused || document.hidden);
    for (const el of dialog.querySelectorAll("[data-source-item]"))
      el.hidden = !allowed[el.dataset.sourceItem];
    get("[data-no-sources]").hidden = allowed.shared || allowed.youtube;
    get("[data-sample-context]").hidden = stage === 0 || !assigned.length;
    get("[data-sample-movement]").hidden = phase !== "movement";
    get("[data-sample-questions]").hidden = phase !== "questions";
    get("[data-sample-results]").hidden = stage < 2 || !assigned.length;
    get("[data-assignment]").textContent =
      assigned.length === 1 ? words.single.replace("{name}", authors[assigned[0]]) : words.dispatch;
    const progress = Math.min(stage, 3);
    [...dialog.querySelectorAll("[data-track]")].forEach((el, index) => {
      el.dataset.progress =
        !assigned.length || index > progress ? "upcoming" : index === progress ? "current" : "done";
      if (assigned.length && index === progress) el.setAttribute("aria-current", "step");
      else el.removeAttribute("aria-current");
    });
    let count = 0;
    for (const key of Object.keys(authors)) {
      const lane = get(`[data-agent="${key}"]`);
      const selected = assigned.includes(key);
      const filed = selected && (stage === 4 || (stage === 3 && key === assigned[0]));
      lane.dataset.state = !selected ? "off" : filed ? "filed" : stage >= 2 ? "working" : "queued";
      lane.hidden = !selected;
      lane.querySelector("[data-agent-state]").textContent = filed ? words.filed : words.research;
      lane.querySelector("[data-agent-pending]").hidden = filed;
      lane.querySelector("article").hidden = !filed;
      if (filed) count++;
    }
    get("#fc-results-title").textContent = count ? words.returned : words.research;
    get("[data-sample-count]").dataset.count = String(count);
    get("[data-sample-count]").textContent = words.counts[count];
    const empty = get("[data-sample-empty]");
    empty.hidden = !!assigned.length;
    empty.textContent = allowed.shared ? words.unassigned : words.denied;
    const play = get("[data-sample-pause]");
    play.disabled = !assigned.length;
    play.textContent = paused || !assigned.length ? words.resume : words.pause;
    const notice = [
      words.movement,
      words.why + " " + words.next,
      words.research,
      words.counts[count],
      words.returned + " · " + words.counts[count],
    ];
    get("[data-run-status]").textContent = !assigned.length ? empty.textContent : notice[stage];
  }

  function cancelTimer() {
    if (timer === null) return;
    clearTimeout(timer);
    timer = null;
    remaining = Math.max(0, remaining - (performance.now() - started));
  }

  function schedule() {
    if (
      !dialog.open ||
      document.hidden ||
      paused ||
      timer !== null ||
      dialog.dataset.phase === "blocked"
    )
      return;
    started = performance.now();
    timer = setTimeout(advance, remaining);
  }

  function advance() {
    cancelTimer();
    if (dialog.dataset.phase === "blocked") return;
    const allowed = scope();
    stage = stage === 2 && !(allowed.chatgpt && allowed.muse) ? 4 : (stage + 1) % phases.length;
    remaining = durations[stage];
    render();
    schedule();
  }

  function startRun({ resetPlayback = false } = {}) {
    cancelTimer();
    stage = 0;
    if (resetPlayback) paused = motion.matches;
    remaining = durations[stage];
    const graphic = get("[data-sample-movement]");
    // A new assignment restarts the chart even if the first stage is already visible.
    graphic.hidden = true;
    graphic.getBoundingClientRect();
    render();
    schedule();
  }

  function setLanguage(value) {
    language = /^zh/i.test(value) ? (/hant|tw|hk|mo/i.test(value) ? "zh-Hant" : "zh-Hans") : "en";
    dialog.lang = language;
    const words = messages[language];
    for (const el of dialog.querySelectorAll("[data-word]"))
      el.textContent = words[el.dataset.word];
    for (const el of dialog.querySelectorAll("[data-label]"))
      el.setAttribute("aria-label", words[el.dataset.label]);
    render();
  }
  document.addEventListener("folio-language", (event) =>
    setLanguage(event.detail?.lang || document.documentElement.lang),
  );
  document.addEventListener("click", (event) => {
    const trigger = event.target.closest?.("[data-open-demo]");
    if (!trigger || dialog.open) return;
    event.preventDefault();
    opener = trigger;
    setLanguage(document.documentElement.lang);
    get("[data-sample-access]").open = false;
    dialog.showModal();
    get(".sample-scroll").scrollTop = 0;
    get("#fc-sample-title").focus({ preventScroll: true });
    document.dispatchEvent(new CustomEvent("folio-demo", { detail: { open: true } }));
    startRun({ resetPlayback: true });
  });
  get("[data-sample-close]").addEventListener("click", () => dialog.close());
  get("[data-sample-pause]").addEventListener("click", () => {
    cancelTimer();
    paused = !paused;
    render();
    schedule();
  });
  document.addEventListener("visibilitychange", () => {
    if (!dialog.open) return;
    cancelTimer();
    render();
    schedule();
  });
  dialog.addEventListener("change", () => {
    startRun();
    document.dispatchEvent(new CustomEvent("folio-scope", { detail: scope() }));
  });
  motion.addEventListener("change", () => {
    if (!dialog.open || !motion.matches) return;
    cancelTimer();
    paused = true;
    render();
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const controls = [...dialog.querySelectorAll("button:enabled, summary, input:enabled")].filter(
      (el) =>
        el.getClientRects().length > 0 &&
        (!el.closest("details:not([open])") || el.tagName === "SUMMARY"),
    );
    const first = controls[0];
    const last = controls.at(-1);
    if (event.shiftKey && [first, get("#fc-sample-title")].includes(document.activeElement)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  dialog.addEventListener("close", () => {
    if (dialog.open) return;
    cancelTimer();
    if (opener?.isConnected) opener.focus({ preventScroll: true });
    opener = null;
    document.dispatchEvent(new CustomEvent("folio-demo", { detail: { open: false } }));
  });
  let backdropPress = false;
  dialog.addEventListener("pointerdown", (event) => {
    backdropPress = event.target === dialog;
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog && backdropPress) dialog.close();
    backdropPress = false;
  });
  setLanguage(document.documentElement.lang);
})();
