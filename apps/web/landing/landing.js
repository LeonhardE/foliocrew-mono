(() => {
  "use strict";
  const deck = document.querySelector("#deck");
  const chapters = [...deck.querySelectorAll(".chapter")];
  const jumps = [...deck.querySelectorAll("[data-jump]")];
  const languageSelect = document.querySelector("#language");
  const pauseButton = document.querySelector("#pause");
  const prefersReduced = matchMedia("(prefers-reduced-motion: reduce)");
  const duration = 9000;
  const texts = [...deck.querySelectorAll("[data-text]")];
  const english = Object.fromEntries(texts.map((el) => [el.dataset.text, el.textContent]));
  Object.assign(english, {
    deck: "Foliocrew product introduction",
    s0: "Overview",
    controls: "Presentation controls",
    choose: "Choose a scene",
    prev: "Previous scene",
    next: "Next scene",
    pause: "Pause presentation",
    play: "Play presentation",
    language: "Language",
  });
  const dictionaries = {
    en: english,
    "zh-Hans": {
      category: "投资研究 Agent 平台",
      t0a: "持仓跌了，",
      t0b: "接下来怎么办？",
      b0: "Cedar 股价回落，其他持仓持平。把同一次变动交给 ChatGPT 和 Muse，看看它们怎么判断。",
      s1: "资源库",
      t1a: "这次研究，",
      t1b: "用哪些资料？",
      b1: "从资源库选一份持仓快照。需要时，也可以附上你关注的 YouTube 频道。",
      s2: "任务中心",
      t2a: "为什么跌了？",
      t2b: "下一步呢？",
      b2: "把这两个问题同时交给 ChatGPT 和 Muse。两位 Agent 拿到相同的资料，各自分析。",
      s3: "研究报告",
      t3a: "打开任务，",
      t3b: "对照两份分析。",
      b3: "ChatGPT 发现，股数没变，市值随报价回落。Muse 建议查查公司公告，再对照同期行业走势。",
      s4: "隐私保护",
      t4a: "分享给谁，",
      t4b: "由你决定。",
      b4: "用设备通行密钥解锁私人资料。你随时可以撤销 Agent 的访问权限，对方已经收到的副本会保留。",
      enter: "进入工作台",
      demo: "看研究演示",
      deck: "Foliocrew 产品介绍",
      s0: "概览",
      controls: "播放控制",
      choose: "选择章节",
      prev: "上一幕",
      next: "下一幕",
      pause: "暂停播放",
      play: "继续播放",
      language: "语言",
    },
    "zh-Hant": {
      category: "投資研究 Agent 平台",
      t0a: "持股跌了，",
      t0b: "接下來怎麼辦？",
      b0: "Cedar 股價回落，其他持股表現平穩。請 ChatGPT 和 Muse 各自分析，再比較兩者的看法。",
      s1: "資源庫",
      t1a: "這次研究，",
      t1b: "要用哪些資料？",
      b1: "從資源庫挑一份持倉快照。有需要的話，也能附上你訂閱的 YouTube 頻道。",
      s2: "任務中心",
      t2a: "為什麼跌了？",
      t2b: "下一步呢？",
      b2: "把這兩個問題同時交給 ChatGPT 和 Muse。兩位 Agent 各自根據同一份資料提出看法。",
      s3: "研究報告",
      t3a: "打開任務，",
      t3b: "比較兩份分析。",
      b3: "ChatGPT 發現，持股數量沒變，市值隨股價下滑。Muse 建議比對公司公告與同期產業走勢，找出值得追查的線索。",
      s4: "隱私保護",
      t4a: "要分享給誰，",
      t4b: "由你決定。",
      b4: "用裝置的通行金鑰解鎖私人資料。你可以隨時撤回 Agent 的存取權，對方會保留已收到的副本。",
      enter: "進入工作台",
      demo: "看研究示範",
      deck: "Foliocrew 產品介紹",
      s0: "概覽",
      controls: "播放控制",
      choose: "選擇章節",
      prev: "上一幕",
      next: "下一幕",
      pause: "暫停播放",
      play: "繼續播放",
      language: "語言",
    },
  };
  const scopeCopy = {
    en: {
      holdingsOnly: "The agents receive only the holdings snapshot for this task.",
      noSource: "Share the holdings snapshot so the agents can investigate the move.",
      noAgent: "Choose an agent to investigate the move.",
      waitHead: "Before research",
      waitTail: "can begin…",
      resultsHead: "This task",
      resultsWaiting: "is on hold.",
      singleHead: "Open the task.",
      singleTail: "Read the report.",
      oneBody: "You’ve assigned this research to {name}. Its report will appear in the task.",
      gpt: "ChatGPT finds the share count held steady. The lower quote accounts for the change in holding value.",
      muse: "Muse suggests comparing company announcements with the sector’s performance.",
    },
    "zh-Hans": {
      holdingsOnly: "这次只分享持仓快照，YouTube 订阅仍保存在资源库。",
      noSource: "先共享持仓快照，Agent 才能分析这次变动。",
      noAgent: "选一位 Agent 来分析这次持仓变动。",
      waitHead: "准备好后，",
      waitTail: "就能开始研究。",
      resultsHead: "任务还没开始，",
      resultsWaiting: "报告稍后生成。",
      singleHead: "打开任务，",
      singleTail: "查看研究结果。",
      oneBody: "这次由 {name} 分析持仓变动。完成后，你可以在任务里查看报告。",
      gpt: "ChatGPT 发现持股数量没变，较低的报价解释了这次市值回落。",
      muse: "Muse 建议对照同期的公司公告和行业走势，查找下跌的线索。",
    },
    "zh-Hant": {
      holdingsOnly: "這次只分享持倉快照，YouTube 訂閱仍保存在資源庫。",
      noSource: "先分享持倉快照，Agent 才能分析這次變動。",
      noAgent: "選一位 Agent 來研究這次持股下跌的原因。",
      waitHead: "準備好後，",
      waitTail: "就能開始研究。",
      resultsHead: "任務還沒開始，",
      resultsWaiting: "報告稍後產生。",
      singleHead: "打開任務，",
      singleTail: "查看分析結果。",
      oneBody: "這次由 {name} 分析持股變動。完成後，你可以在任務裡查看報告。",
      gpt: "ChatGPT 發現持股數量沒變，這次市值下滑來自股價回落。",
      muse: "Muse 建議比對同期的公司公告與產業走勢，找出可能的原因。",
    },
  };
  let scope = { shared: true, chatgpt: true, muse: true, youtube: true };
  function renderStory() {
    const copy = { ...dictionaries[language] };
    const variant = scopeCopy[language];
    if (!scope.youtube) copy.b1 = variant.holdingsOnly;
    if (!scope.shared || (!scope.chatgpt && !scope.muse)) {
      const message = scope.shared ? variant.noAgent : variant.noSource;
      Object.assign(copy, {
        t0a: variant.waitHead,
        t0b: variant.waitTail,
        b0: message,
        b2: message,
        t3a: variant.resultsHead,
        t3b: variant.resultsWaiting,
        b3: message,
      });
      if (!scope.shared) copy.b1 = message;
    } else if (!scope.chatgpt || !scope.muse) {
      const brief = variant.oneBody.replace("{name}", scope.chatgpt ? "ChatGPT" : "Muse");
      Object.assign(copy, {
        t0a: copy.t2a,
        t0b: copy.t2b,
        b0: brief,
        b2: brief,
        t3a: variant.singleHead,
        t3b: variant.singleTail,
        b3: scope.chatgpt ? variant.gpt : variant.muse,
      });
    }
    for (const el of texts) el.textContent = copy[el.dataset.text];
  }
  const requestedLanguage = new URL(location.href).searchParams.get("lang");
  let language = Object.hasOwn(dictionaries, requestedLanguage) ? requestedLanguage : "en";
  let index = Math.max(
    0,
    chapters.findIndex((el) => "#" + el.id === location.hash),
  );
  let userPaused = prefersReduced.matches;
  let modalOpen = false;
  let timeout = null;
  let started = 0;
  let elapsed = 0;
  const flow = () => window.FolioFlow;
  function syncClock() {
    if (timeout !== null) {
      elapsed = Math.min(duration, elapsed + performance.now() - started);
      clearTimeout(timeout);
      timeout = null;
    }
    const running = !userPaused && !document.hidden && !modalOpen;
    deck.dataset.playing = String(running);
    const state = dictionaries[language][userPaused ? "play" : "pause"];
    pauseButton.setAttribute("aria-label", state);
    pauseButton.title = state;
    flow()?.setPaused(!running);
    const fill = jumps[index].querySelector("i");
    fill.style.transition = "none";
    fill.style.transform = "scaleX(" + elapsed / duration + ")";
    if (!running) return;
    const remaining = Math.max(0, duration - elapsed);
    // Commit the elapsed position before starting the next linear segment.
    fill.getBoundingClientRect();
    fill.style.transition = "transform " + remaining + "ms linear";
    fill.style.transform = "scaleX(1)";
    started = performance.now();
    timeout = setTimeout(() => show(index + 1, false), remaining);
  }
  function show(value, manual) {
    clearTimeout(timeout);
    timeout = null;
    elapsed = 0;
    index = (value + chapters.length) % chapters.length;
    deck.dataset.index = String(index);
    chapters.forEach((section, i) => {
      section.hidden = index !== i;
      section.classList.toggle("arrive", index === i);
      const button = jumps[i];
      if (i === index) button.setAttribute("aria-current", "step");
      else button.removeAttribute("aria-current");
      const fill = button.querySelector("i");
      fill.style.transition = "none";
      fill.style.transform = i < index ? "scaleX(1)" : "scaleX(0)";
    });
    document.querySelector("#ordinal").textContent = String(index + 1).padStart(2, "0");
    if (manual)
      document.querySelector("#announcement").textContent =
        index + 1 + " / 5 · " + dictionaries[language]["s" + index];
    flow()?.show(index);
    syncClock();
  }
  function setLanguage(value) {
    language = value;
    document.documentElement.lang = value;
    languageSelect.value = value;
    const dict = dictionaries[value];
    document.title = "Foliocrew · " + dict.category;
    deck.setAttribute("aria-label", dict.deck);
    document.querySelector('meta[name="description"]').content = dict.b0;
    renderStory();
    for (const el of deck.querySelectorAll("[data-label]")) {
      const name = dict[el.dataset.label];
      el.setAttribute("aria-label", name);
      if (el.tagName === "BUTTON") el.title = name;
    }
    jumps.forEach((jump, i) => {
      const name = i + 1 + " / 5 · " + dict["s" + i];
      jump.setAttribute("aria-label", name);
      jump.title = name;
    });
    flow()?.setLanguage(value);
    document.dispatchEvent(new CustomEvent("folio-language", { detail: { lang: value } }));
    syncClock();
  }
  function togglePlay() {
    userPaused = !userPaused;
    syncClock();
  }
  languageSelect.addEventListener("change", () => {
    setLanguage(languageSelect.value);
    if (/^https?:$/.test(location.protocol)) {
      const url = new URL(location.href);
      url.searchParams.set("lang", language);
      history.replaceState(null, "", url);
    }
  });
  document.querySelector("#prev").onclick = () => show(index - 1, true);
  document.querySelector("#next").onclick = () => show(index + 1, true);
  pauseButton.onclick = togglePlay;
  jumps.forEach((jump, i) => (jump.onclick = () => show(i, true)));
  function openLinkedDemo() {
    if (location.hash === "#task-demo" && !modalOpen) {
      deck.querySelector("[data-open-demo]").click();
    }
  }
  document.addEventListener("folio-demo", (event) => {
    modalOpen = event.detail.open;
    if (!modalOpen && location.hash === "#task-demo" && /^https?:$/.test(location.protocol)) {
      const url = new URL(location.href);
      url.hash = "";
      history.replaceState(null, "", url);
    }
    syncClock();
  });
  window.addEventListener("hashchange", openLinkedDemo);
  document.addEventListener("folio-scope", (event) => {
    scope = event.detail;
    flow()?.setRecipients(scope);
    renderStory();
  });
  document.addEventListener("visibilitychange", syncClock);
  prefersReduced.addEventListener("change", () => {
    userPaused = prefersReduced.matches;
    syncClock();
  });
  document.addEventListener("keydown", (event) => {
    if (modalOpen || event.altKey || event.ctrlKey || event.metaKey || event.isComposing) return;
    if (event.key === "Tab" && !userPaused) {
      userPaused = true;
      syncClock();
    }
    if (event.target.closest("select,input,textarea,dialog")) return;
    const relative = {
      ArrowRight: 1,
      ArrowDown: 1,
      PageDown: 1,
      ArrowLeft: -1,
      ArrowUp: -1,
      PageUp: -1,
    };
    if (Object.hasOwn(relative, event.key)) {
      event.preventDefault();
      show(index + relative[event.key], true);
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      show(event.key === "Home" ? 0 : chapters.length - 1, true);
    } else if (event.code === "Space" && !event.target.closest("button,a")) {
      event.preventDefault();
      togglePlay();
    }
  });
  // One gesture advances once, including precision trackpads with inertial tails.
  let wheelTotal = 0,
    lastWheel = 0,
    usedWheel = false;
  deck.addEventListener(
    "wheel",
    (event) => {
      if (
        modalOpen ||
        event.ctrlKey ||
        event.target.closest("select,dialog") ||
        deck.offsetHeight > innerHeight + 4
      )
        return;
      const d = Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? event.deltaY : event.deltaX;
      if (!d) return;
      event.preventDefault();
      const now = performance.now();
      if (now - lastWheel > 180) {
        wheelTotal = 0;
        usedWheel = false;
      }
      lastWheel = now;
      wheelTotal += d * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? innerHeight : 1);
      if (!usedWheel && Math.abs(wheelTotal) > 32) {
        usedWheel = true;
        show(index + Math.sign(wheelTotal), true);
      }
    },
    { passive: false },
  );
  let touch = null;
  deck.addEventListener(
    "touchstart",
    (event) => {
      touch = null;
      if (
        !modalOpen &&
        event.touches.length === 1 &&
        !event.target.closest("button,a,select,dialog")
      ) {
        touch = [event.touches[0].clientX, event.touches[0].clientY];
      }
    },
    { passive: true },
  );
  deck.addEventListener("touchcancel", () => {
    touch = null;
  });
  deck.addEventListener(
    "touchend",
    (event) => {
      if (!touch || modalOpen) return;
      const dx = touch[0] - event.changedTouches[0].clientX,
        dy = touch[1] - event.changedTouches[0].clientY;
      touch = null;
      if (deck.offsetHeight > innerHeight + 4 && Math.abs(dy) > Math.abs(dx)) return;
      const swipe = Math.abs(dx) > Math.abs(dy) ? dx : dy;
      if (Math.abs(swipe) > 45) show(index + Math.sign(swipe), true);
    },
    { passive: true },
  );
  window.addEventListener("pagehide", () => {
    clearTimeout(timeout);
    timeout = null;
    flow()?.setPaused(true);
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) syncClock();
  });
  document.documentElement.classList.add("js");
  setLanguage(language);
  show(index, false);
  openLinkedDemo();
})();
