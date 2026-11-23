import { NativeAccountBridge } from "./account-bridge.mjs";
const messages = {
  en: {
    title: "Connect your Agent to Foliocrew",
    intro:
      "Confirm your Foliocrew account, then return to your Agent. You can choose which resources and tasks to share when you finish connecting.",
    continue: "Continue to Foliocrew",
    return: "Return to Agent",
    confirmed: "Foliocrew account confirmed. If you are still here, select Return to Agent.",
    opened: "Confirm your account in the Foliocrew window, then return to this page.",
    popup: "Allow the Foliocrew window to open, then try again.",
    unavailable: "This connection request is unavailable. Try again from your Agent.",
  },
  zh: {
    title: "连接 Agent 与 Foliocrew",
    intro: "先确认 Foliocrew 账号，再返回 Agent。完成配对时，你可以选择允许使用的资料和任务。",
    continue: "继续到 Foliocrew",
    return: "返回 Agent",
    confirmed: "已确认 Foliocrew 账号。若没有自动跳转，请点「返回 Agent」。",
    opened: "请在新打开的 Foliocrew 工作台确认账号，然后回到此页面。",
    popup: "请允许打开 Foliocrew 页面后重试。",
    unavailable: "连接请求暂时不可用，请从 Agent 重试。",
  },
  "zh-Hant": {
    title: "連線 Agent 與 Foliocrew",
    intro: "先確認 Foliocrew 帳號，再返回 Agent。完成配對時，你可以選擇允許使用的資料和任務。",
    continue: "繼續前往 Foliocrew",
    return: "返回 Agent",
    confirmed: "已確認 Foliocrew 帳號。若未自動跳轉，請點選「返回 Agent」。",
    opened: "請在新開啟的 Foliocrew 工作台確認帳號，再返回此頁面。",
    popup: "請允許開啟 Foliocrew 頁面後再試一次。",
    unavailable: "連線請求暫時無法使用，請從 Agent 重試。",
  },
};
const preferred = (navigator.languages.length ? navigator.languages : [navigator.language]).find(
  (locale) => /^(en|zh)(-|$)/i.test(locale),
);
const [base, ...qualifiers] = (preferred ?? "en").toLowerCase().split("-");
const traditional =
  qualifiers.includes("hant") ||
  (!qualifiers.includes("hans") && qualifiers.some((part) => ["tw", "hk", "mo"].includes(part)));
const language = base === "zh" ? (traditional ? "zh-Hant" : "zh") : "en";
const copy = messages[language];
const status = document.querySelector("#status"),
  button = document.querySelector("#continue"),
  returnLink = document.querySelector("#return-to-agent");
document.documentElement.lang = language === "zh" ? "zh-CN" : language;
document.title = document.querySelector("h1").textContent = copy.title;
status.textContent = copy.intro;
button.textContent = copy.continue;
returnLink.textContent = copy.return;
try {
  const q = new URLSearchParams(location.search);
  if ([...q.keys()].join(",") !== "request") throw Error("invalid_request");
  const r = await fetch("/agent/v3/account/config", {
    cache: "no-store",
    credentials: "omit",
    redirect: "error",
  });
  if (!r.ok) throw Error("unavailable");
  const config = await r.json();
  const bridge = new NativeAccountBridge({
    config,
    requestId: q.get("request"),
    navigate: (callback) => {
      // The bridge passes only the validated callback for this request.
      returnLink.href = callback;
      returnLink.hidden = false;
      try {
        location.assign(callback);
      } catch {
        // Some embedded browsers require the user to follow the callback link.
      }
    },
    onState: (state) => {
      if (state === "connected") {
        button.hidden = true;
        status.textContent = copy.confirmed;
      } else if (state === "owner_opened" || state === "owner_attached")
        status.textContent = copy.opened;
    },
  });
  button.hidden = false;
  button.onclick = () => {
    try {
      bridge.open(config.ownerOrigins[0]);
      button.disabled = true;
    } catch {
      status.textContent = copy.popup;
    }
  };
} catch {
  status.textContent = copy.unavailable;
}
