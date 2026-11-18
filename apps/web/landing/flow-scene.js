/* Foliocrew's document journey. Geometry is projected directly from a small
   three-dimensional scene so it also runs on devices without WebGL. */
(() => {
  "use strict";

  const stage = document.getElementById("flow-stage");
  if (!stage) return;
  const canvas = document.createElement("canvas");
  canvas.className = "flow-optics";
  canvas.setAttribute("aria-hidden", "true");
  stage.append(canvas);
  const ctx = typeof Path2D === "function" ? canvas.getContext("2d") : null;
  const lightMode = matchMedia("(prefers-color-scheme: light)");
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
  const labels = {
    en: {
      example: "Fictional holding",
      change: "Cedar moved lower",
      fullQuestion: "Why? Now What?",
      snapshot:
        "Cedar is a fictional holding. Its latest market value is lower than in the previous snapshot.",
      chatgpt: {
        title: "Price impact",
        finding:
          "The share count is unchanged. A lower quote explains the fall in the holding’s value. The reason the market price fell is still unknown.",
      },
      muse: {
        title: "Check news",
        finding:
          "Check the issuer’s announcements against the quote time and compare the move with its industry before deciding whether to act.",
      },
      single:
        "Only {agent} receives the two questions. Its signed report returns to the original task in the Task center.",
    },
    "zh-Hans": {
      example: "虚构持仓",
      change: "Cedar 持仓市值回落",
      fullQuestion: "持仓市值为什么下降？现在该做什么？",
      snapshot: "Cedar 是一项虚构持仓。与上次快照相比，这次记录的持仓市值有所回落。",
      chatgpt: {
        title: "价格影响",
        finding: "持股数量没变，每股报价走低，因此持仓市值回落。报价下跌的原因还有待证实。",
      },
      muse: {
        title: "核查公告",
        finding: "先核对发行方公告与报价的时间，并比较同期行业走势，再决定是否需要行动。",
      },
      single: "只有 {agent} 收到这两个问题，署名报告归入任务中心的原任务。",
    },
    "zh-Hant": {
      example: "虛構持倉",
      change: "Cedar 持倉市值回落",
      fullQuestion: "持倉市值為何下降？現在該怎麼做？",
      snapshot: "Cedar 是一項虛構持倉。與上次快照相比，這次記錄的持倉市值有所回落。",
      chatgpt: {
        title: "價格影響",
        finding: "持股數量沒變，每股報價走低，因此持倉市值回落。報價下跌的原因仍有待證實。",
      },
      muse: {
        title: "查核公告",
        finding: "先核對發行方公告與報價的時間，並比較同期產業走勢，再決定是否需要行動。",
      },
      single: "只有 {agent} 收到這兩個問題，署名報告歸入任務中心的原任務。",
    },
  };

  const studio = {
    en: {
      library: "Resources",
      desk: "Task center",
      context: "The authorized bundle includes the holdings snapshot and YouTube subscriptions.",
      only: "Only the holdings snapshot is shared. YouTube subscriptions stay in Resources.",
      none: "The holdings stay private in Resources. The agents need this snapshot to investigate the change and deliver reports.",
      unassigned: "No robot is assigned. The Task center has no new reports.",
      scenes: [
        "Two robots collect the same task and bring their independent reports to the Task center.",
        "In Resources, the safe opens to show the blue holdings folder and red YouTube subscriptions card.",
        "ChatGPT and Muse receive the same two questions and authorized files. Each prepares its own response.",
        "Both signed reports are filed under the original task in the Task center.",
        "The safe door protects the original files. Only authorized copies accompany the shared task.",
      ],
    },
    "zh-Hans": {
      library: "资源库",
      desk: "任务中心",
      context: "已授权资料包含持仓快照和 YouTube 订阅。",
      only: "本任务仅获准使用持仓快照，YouTube 订阅留在资源库。",
      none: "持仓未授权。机器人需要持仓快照才能调查变动并交付报告。",
      unassigned: "任务尚未指定机器人，任务中心暂无本轮报告。",
      scenes: [
        "两台机器人接下同一项任务，把各自的署名报告送回任务中心。",
        "资源库的保险柜门打开，蓝色持仓文件夹与红色 YouTube 订阅卡放在架上。",
        "ChatGPT 和 Muse 领到相同的两个问题和同一组已授权的资料，各自准备报告。",
        "两份署名报告归入任务中心的原任务。",
        "保险柜保护原始资料，只有已授权的副本可以随任务交付。",
      ],
    },
    "zh-Hant": {
      library: "資源庫",
      desk: "任務中心",
      context: "已授權資料包含持倉快照和 YouTube 訂閱。",
      only: "這項任務僅獲准使用持倉快照，YouTube 訂閱留在資源庫。",
      none: "持倉未授權。機器人需要持倉快照才能調查變動並交付報告。",
      unassigned: "任務尚未指定機器人，任務中心暫無這次的報告。",
      scenes: [
        "兩台機器人接下同一項任務，把各自的署名報告送回任務中心。",
        "資源庫的保險箱門打開，藍色持倉資料夾與紅色 YouTube 訂閱卡放在架上。",
        "ChatGPT 和 Muse 領到相同的兩個問題和同一組已授權的資料，各自準備報告。",
        "兩份署名報告歸入任務中心的原任務。",
        "保險箱保護原始資料，只有已授權的副本可以隨任務交付。",
      ],
    },
  };
  // Positions are in world space; the five chapters frame the same studio.
  const shots = [
    [0, 0.98, 0, -0.3, 0.47, 12.0, 6.4],
    [-2.75, 1.34, -0.25, -0.36, 0.36, 6.7, 4.9],
    [-0.94, 1.05, -0.15, -0.22, 0.48, 8.2, 5.15],
    [2.15, 0.95, 0.24, -0.45, 0.52, 7.4, 4.2],
    [-2.88, 1.28, -0.13, -0.26, 0.44, 6.45, 4.6],
  ];
  const vault = [-3.03, 0, -0.72],
    task = [-0.67, 0, -1.88],
    desk = [3.05, 0, 0.22];
  const chosen = { shared: true, youtube: true, chatgpt: true, muse: true };
  const camera = shots[0].slice(),
    stillPhases = [0.59, 0.42, 0.58, 0.93, 0.96];
  let active = 0,
    language = "en",
    paused = false,
    visible = true;
  let frame = 0,
    last = 0,
    phase = 0.035,
    drift = 0,
    completedLoop = false,
    cw = 1,
    ch = 1,
    ratio = 1;
  let scale = 1,
    ca = 1,
    sa = 0,
    ce = 1,
    se = 0,
    light = lightMode.matches;
  const TAU = Math.PI * 2;
  const clamp = (x, min = 0, max = 1) => Math.max(min, Math.min(max, x));
  const mix = (a, b, t) => a + (b - a) * t;
  const wave = (x) => (1 - Math.cos(clamp(x) * Math.PI)) / 2;
  const tint = (c, a) => "rgba(" + c + "," + a + ")";
  const materials = {
    source: {
      accent: "125,160,255",
      top: "#859ee7",
      mid: "#4a67ab",
      side: "#273b6a",
      shadow: "#15213c",
      paper: "#e5ebff",
      ink: "#244478",
      narrow: "#778bb6",
    },
    chatgpt: {
      accent: "202,206,211",
      top: "#cfcece",
      mid: "#6d7176",
      side: "#45484c",
      shadow: "#25272b",
      paper: "#fffefb",
      ink: "#151619",
      narrow: "#929599",
    },
    muse: {
      accent: "106,179,255",
      top: "#7fb6fc",
      mid: "#0082fb",
      side: "#0064e0",
      shadow: "#193979",
      paper: "#f2f7ff",
      ink: "#0040dc",
      narrow: "#708ebd",
    },
    result: {
      accent: "157,187,246",
      top: "#a4b7d8",
      mid: "#667fa6",
      side: "#384e71",
      shadow: "#25344d",
      paper: "#ebf2ff",
      ink: "#334863",
      narrow: "#8a98ac",
    },
    locked: {
      accent: "143,157,187",
      top: "#939bab",
      mid: "#667383",
      side: "#4b5465",
      shadow: "#343d49",
      paper: "#c0c7d2",
      ink: "#394252",
      narrow: "#758091",
    },
  };
  Object.assign(materials, {
    metal: {
      accent: "171,191,225",
      top: "#b1bed9",
      mid: "#7787a7",
      side: "#455572",
      shadow: "#2b374c",
      paper: "#ecf3ff",
      ink: "#263d58",
      narrow: "#a1aec5",
    },
    wood: {
      accent: "232,191,143",
      top: "#e6c199",
      mid: "#bd916d",
      side: "#956f56",
      shadow: "#654d41",
      paper: "#f7e4bc",
      ink: "#553d31",
      narrow: "#b29573",
    },
    dark: {
      accent: "122,145,172",
      top: "#52637b",
      mid: "#35445a",
      side: "#273246",
      shadow: "#182333",
      paper: "#ebf3ff",
      ink: "#20304c",
      narrow: "#899ab5",
    },
    coral: {
      accent: "255,136,126",
      top: "#ffaba1",
      mid: "#ed766f",
      side: "#ad4c50",
      shadow: "#67323f",
      paper: "#fff0e9",
      ink: "#7f3440",
      narrow: "#ba7879",
    },
  });
  function project(x, y, z) {
    const dx = x - camera[0],
      dy = y - camera[1],
      dz = z - camera[2];
    const sideways = dx * ca + dz * sa,
      toward = dz * ca - dx * sa;
    const depth = toward * ce + dy * se;
    const size = scale / (1 - depth * 0.029);
    return [cw * 0.5 + sideways * size, ch * 0.52 + (toward * se - dy * ce) * size, depth];
  }
  function projectPoint(p) {
    return project(p[0], p[1], p[2]);
  }
  function screenPath(points, close = false) {
    ctx.beginPath();
    points.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])));
    if (close) ctx.closePath();
  }
  function face(points, fill, stroke, width = 0.7) {
    screenPath(points.map(projectPoint), true);
    if (fill) {
      ctx.fillStyle = fill;
      ctx.fill();
    }
    if (stroke) {
      ctx.strokeStyle = stroke;
      ctx.lineWidth = width;
      ctx.stroke();
    }
  }
  function line(points, ink, width = 1) {
    screenPath(points.map(projectPoint));
    ctx.strokeStyle = ink;
    ctx.lineWidth = width;
    ctx.stroke();
  }
  function gradient(p, q, colors) {
    const g = ctx.createLinearGradient(p[0], p[1], q[0], q[1]);
    colors.forEach(([t, c]) => g.addColorStop(t, c));
    return g;
  }

  function footprint(x, z, w, d, r) {
    const a = w / 2,
      b = d / 2;
    return [
      [-a + r, -b],
      [a - r, -b],
      [a, -b + r],
      [a, b - r],
      [a - r, b],
      [-a + r, b],
      [-a, b - r],
      [-a, -b + r],
    ].map(([u, v]) => [x + u, z + v]);
  }
  // A bevelled solid with a highlight that travels across its polished edge.
  function slab(x, y, z, w, d, h, m, style = "glass") {
    const f = footprint(x, z, w, d, Math.min(w, d) * 0.13),
      bottom = f.map(([u, v]) => [u, y, v]),
      top = f.map(([u, v]) => [u, y + h, v]);
    const sides = f
      .map((_, i) => {
        const j = (i + 1) % f.length;
        return {
          points: [bottom[i], bottom[j], top[j], top[i]],
          depth: (projectPoint(top[i])[2] + projectPoint(top[j])[2]) / 2,
          i,
        };
      })
      .sort((a, b) => a.depth - b.depth);
    for (const side of sides) {
      const a = projectPoint(side.points[0]),
        b = projectPoint(side.points[2]);
      const color =
        style === "paper"
          ? gradient(a, b, [
              [0, m.narrow],
              [1, m.paper],
            ])
          : gradient(a, b, [
              [0, m.shadow],
              [0.42, m.side],
              [0.83, m.mid],
              [1, m.top],
            ]);
      face(side.points, color, tint(m.accent, style === "paper" ? 0.24 : 0.33), 0.65);
    }
    const a = projectPoint(top[0]),
      b = projectPoint(top[4]);
    const topInk =
      style === "paper"
        ? gradient(a, b, [
            [0, m.paper],
            [0.72, m.paper],
            [1, m.narrow],
          ])
        : gradient(a, b, [
            [0, m.mid],
            [0.31, m.top],
            [0.56, m.mid],
            [0.9, m.side],
            [1, m.top],
          ]);
    face(top, topInk, tint(m.accent, 0.94), 1);
    if (style === "glass") {
      const inset = footprint(x, z, w * 0.91, d * 0.86, Math.min(w, d) * 0.1).map(([u, v]) => [
        u,
        y + h + 0.002,
        v,
      ]);
      face(inset, null, tint(m.accent, 0.58), 0.66);
    }
  }
  function shadow(x, z, w, d, strength = 0.4) {
    const center = project(x, 0.02, z),
      right = project(x + w, 0.02, z),
      far = project(x, 0.02, z + d);
    ctx.save();
    ctx.transform(
      right[0] - center[0],
      right[1] - center[1],
      far[0] - center[0],
      far[1] - center[1],
      center[0],
      center[1],
    );
    const g = ctx.createRadialGradient(0, 0, 0.05, 0, 0, 1);
    g.addColorStop(
      0,
      light ? "rgba(32,49,84," + strength * 0.63 + ")" : "rgba(0,5,20," + strength + ")",
    );
    g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = g;
    ctx.fillRect(-1, -1, 2, 2);
    ctx.restore();
  }
  function stageFloor() {
    ctx.save();
    const center = project(0, 0, 0),
      rad = Math.max(cw, ch) * 0.53;
    const g = ctx.createRadialGradient(center[0], center[1], 0, center[0], center[1], rad);
    g.addColorStop(0, light ? "rgba(88,119,178,.19)" : "rgba(98,134,202,.25)");
    g.addColorStop(0.65, light ? "rgba(78,105,150,.11)" : "rgba(77,105,165,.14)");
    g.addColorStop(1, "rgba(60,85,130,0)");
    ctx.strokeStyle = g;
    ctx.lineWidth = 0.65;
    const segments = [];
    for (let j = -10; j <= 10; j++) {
      segments.push(
        [project(j * 0.72, 0, -7), project(j * 0.72, 0, 7)],
        [project(-8, 0, j * 0.72), project(8, 0, j * 0.72)],
      );
    }
    ctx.beginPath();
    for (const [a, b] of segments) {
      ctx.moveTo(a[0], a[1]);
      ctx.lineTo(b[0], b[1]);
    }
    ctx.stroke();
    ctx.restore();
  }

  function tube(a, b, ink, w = 0.055, shine = null) {
    const p = projectPoint(a),
      q = projectPoint(b);
    screenPath([p, q]);
    ctx.lineCap = "round";
    ctx.strokeStyle = ink;
    ctx.lineWidth = Math.max(0.7, w * scale);
    ctx.stroke();
    if (shine) {
      ctx.lineWidth = Math.max(0.55, w * scale * 0.26);
      ctx.strokeStyle = shine;
      ctx.stroke();
    }
  }
  function pearl(x, y, z, rx, ry, base, gleam, edge = "#2f4655") {
    const c = project(x, y, z),
      w = Math.max(0.1, rx * scale),
      h = Math.max(0.1, ry * scale);
    ctx.save();
    ctx.translate(c[0], c[1]);
    ctx.scale(w, h);
    const g = ctx.createRadialGradient(-0.31, -0.37, 0.02, 0.07, 0.13, 1.13);
    g.addColorStop(0, gleam);
    g.addColorStop(0.31, base);
    g.addColorStop(0.82, base);
    g.addColorStop(1, edge);
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(0, 0, 1, 0, TAU);
    ctx.fill();
    ctx.restore();
  }
  // Printed paper, the writing board and the safe door carry their ink on the
  // same world-space surface as the solid behind them.
  function onSurface(origin, right, down, w, h, draw) {
    const o = projectPoint(origin),
      r = projectPoint(right),
      d = projectPoint(down);
    ctx.save();
    ctx.transform(
      (r[0] - o[0]) / w,
      (r[1] - o[1]) / w,
      (d[0] - o[0]) / h,
      (d[1] - o[1]) / h,
      o[0],
      o[1],
    );
    draw();
    ctx.restore();
  }
  function rr(x, y, w, h, r, fill, stroke) {
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, r);
    if (fill) {
      ctx.fillStyle = fill;
      ctx.fill();
    }
    if (stroke) {
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
  }
  // Original provider marks are embedded so playback needs no third-party request.
  // OpenAI Blossom: https://developers.openai.com/favicon.svg (monochrome silhouette).
  // Meta Muse: https://platform.muse.ai/images/muse-logo.svg (original gradient and viewBox).
  const marks = ctx
    ? {
        chatgpt: new Path2D(
          "M9.94494 9.59163V8.13227C9.94494 8.00935 9.99105 7.91713 10.0985 7.85575L13.0327 6.16599C13.4321 5.93558 13.9083 5.8281 14.3998 5.8281C16.2432 5.8281 17.4108 7.25677 17.4108 8.77751C17.4108 8.885 17.4108 9.00792 17.3953 9.13083L14.3537 7.34884C14.1694 7.24135 13.985 7.24135 13.8007 7.34884L9.94494 9.59163ZM16.7963 15.2755V11.7883C16.7963 11.5732 16.704 11.4196 16.5197 11.3121L12.664 9.0693L13.9236 8.34725C14.0311 8.28587 14.1234 8.28587 14.2308 8.34725L17.165 10.037C18.0099 10.5287 18.5782 11.5732 18.5782 12.587C18.5782 13.7544 17.887 14.8298 16.7963 15.2753V15.2755ZM9.03861 12.2031L7.77896 11.4658C7.67146 11.4045 7.62535 11.3122 7.62535 11.1893V7.8098C7.62535 6.16613 8.88501 4.92176 10.5902 4.92176C11.2354 4.92176 11.8344 5.13689 12.3415 5.52089L9.31526 7.27218C9.13097 7.37968 9.03875 7.53328 9.03875 7.74841V12.2033L9.03861 12.2031ZM11.75 13.77L9.94494 12.7562V10.6056L11.75 9.59178L13.5549 10.6056V12.7562L11.75 13.77ZM12.9098 18.44C12.2645 18.44 11.6655 18.2249 11.1585 17.8409L14.1847 16.0896C14.369 15.9821 14.4612 15.8285 14.4612 15.6134V11.1585L15.7363 11.8958C15.8438 11.9572 15.8899 12.0494 15.8899 12.1723V15.5519C15.8899 17.1955 14.6148 18.44 12.9098 18.44ZM9.26901 15.0144L6.33486 13.3246C5.4899 12.833 4.92161 11.7885 4.92161 10.7746C4.92161 9.59177 5.62824 8.53183 6.71886 8.0863V11.5887C6.71886 11.8039 6.81109 11.9575 6.99538 12.065L10.8359 14.2923L9.57621 15.0144C9.46872 15.0758 9.37649 15.0758 9.26901 15.0144ZM9.10013 17.5337C7.36426 17.5337 6.08919 16.2279 6.08919 14.6149C6.08919 14.492 6.1046 14.3691 6.11988 14.2462L9.1461 15.9975C9.33039 16.105 9.51483 16.105 9.69912 15.9975L13.5549 13.7702V15.2295C13.5549 15.3524 13.5088 15.4446 13.4013 15.506L10.4671 17.1958C10.0677 17.4262 9.59148 17.5337 9.09999 17.5337H9.10013ZM12.9098 19.3616C14.7685 19.3616 16.32 18.0406 16.6735 16.2893C18.3939 15.8438 19.5 14.2308 19.5 12.5872C19.5 11.5118 19.0391 10.4673 18.2096 9.71454C18.2864 9.39192 18.3326 9.0693 18.3326 8.74682C18.3326 6.55014 16.5505 4.90634 14.4921 4.90634C14.0774 4.90634 13.6779 4.96772 13.2785 5.10605C12.5872 4.43011 11.6347 4 10.5902 4C8.7314 4 7.17996 5.32103 6.8265 7.07232C5.10605 7.51786 4 9.13083 4 10.7745C4 11.8498 4.4608 12.8944 5.29035 13.6471C5.21354 13.9697 5.16743 14.2923 5.16743 14.6148C5.16743 16.8114 6.94941 18.4552 9.00792 18.4552C9.42261 18.4552 9.82204 18.3939 10.2215 18.2556C10.9127 18.9315 11.8651 19.3616 12.9098 19.3616Z",
        ),
        muse: new Path2D(
          "M24.6257 16.1214C28.2365 16.1214 30.8187 18.9408 30.8187 23.3643C30.8185 27.7868 30.1055 31.7765 28.9225 40.2466C28.0743 46.1813 26.62 55.2418 26.0132 59.0088C27.1782 56.7815 29.9074 51.5757 30.3914 50.5982C36.1081 39.061 42.0657 28.7544 43.7826 26.0254C46.0594 22.382 48.062 20.9229 51.1597 20.9229C52.7685 20.923 54.6826 21.7357 55.6315 22.819C56.9178 24.2895 57.1859 26.6602 57.1411 29.244C57.0738 33.2073 56.5599 39.5264 55.8553 46.5698C55.5416 49.7057 54.9365 56.1066 54.5288 60.4004C58.1883 53.8532 64.9609 41.8109 67.6921 37.6058C70.0727 33.9402 72.466 31.5797 75.6836 31.5796C78.4595 31.5796 81.8809 33.5416 81.6772 38.7573C81.3774 46.4556 80.2673 63.2232 79.7607 70.7479C83.1662 65.7913 87.6377 58.4543 89.3148 55.6966C91.0104 52.908 92.75 50.6542 95.3898 50.5778C98.0987 50.4995 99.913 52.341 99.9959 55.1839C100.078 58.0277 98.3835 61.2256 96.1344 64.856C93.6937 68.7957 90.9621 73.0123 87.6383 76.9491C84.3148 80.8856 81.2604 83.8782 76.5991 83.8786C72.4243 83.8786 69.4869 81.1043 69.283 76.0254C69.1768 73.364 69.6804 67.6405 70.0602 63.1673C70.5 57.9875 71.0315 52.9861 71.403 49.6786C67.7337 56.3979 60.0101 70.4676 56.5348 75.9603C53.1343 81.3339 51.4774 83.2269 47.8882 83.2275C44.2977 83.2275 42.7226 80.6416 42.6717 76.7497C42.6142 72.5285 45.7852 47.1821 46.8587 38.737C45.1183 42.4616 40.839 51.6056 38.1551 57.0435C35.5587 62.3055 31.204 71.3978 28.0436 76.6357C25.7668 80.4094 23.2092 83.2273 19.4173 83.2275C15.6252 83.2275 13.4847 80.6784 13.4847 76.5788C13.4847 72.4794 14.6716 65.6492 15.9465 57.1777C16.5839 53.0781 17.3108 48.6133 18.1315 43.8761C18.7324 40.448 19.7764 34.4169 20.4183 30.7129C17.502 35.2539 12.2536 43.4278 10.6567 45.8903C8.88113 48.6291 7.28747 50.626 4.64681 50.6266C1.7329 50.6266 0.000532901 48.3522 0 45.7113C0 43.0703 1.34323 41.0344 3.52376 37.4512C6.32403 32.8465 11.3578 26.57 14.1154 23.2747C17.3656 19.3912 20.6139 16.1219 24.6257 16.1214Z",
        ),
      }
    : null;
  function brandMark(id, x, y, width, ink = "#17181a") {
    ctx.save();
    ctx.translate(x, y);
    if (id === "chatgpt") {
      ctx.scale(width / 15.5, width / 15.5);
      ctx.translate(-11.75, -11.68);
      ctx.fillStyle = ink;
    } else {
      ctx.scale(width / 100, width / 100);
      ctx.translate(-50, -50);
      const blue = ctx.createLinearGradient(133.245, 109.046, 24.9203, -12.5565);
      blue.addColorStop(0.254808, "#0082fb");
      blue.addColorStop(0.697115, "#0064e0");
      blue.addColorStop(1, "#0040dc");
      ctx.fillStyle = blue;
    }
    ctx.fill(marks[id]);
    ctx.restore();
  }
  function sheet(x, y, z, w, h, kind, { tilt = 0.16, angle = 0, opacity = 1 } = {}) {
    const tri = kind === "youtube",
      holding = kind === "holdings",
      a = kind === "chatgpt",
      reply = a || kind === "muse";
    const m = tri
      ? materials.coral
      : holding
        ? materials.source
        : reply
          ? materials[kind]
          : materials.result;
    const u = [Math.cos(angle), 0, Math.sin(angle)],
      v = [Math.sin(angle) * Math.sin(tilt), Math.cos(tilt), -Math.cos(angle) * Math.sin(tilt)];
    const at = (i, j, depth = 0) => [
      x + (i - 0.5) * w * u[0] + (1 - j) * h * v[0],
      y + (1 - j) * h * v[1] + depth,
      z + (i - 0.5) * w * u[2] + (1 - j) * h * v[2] + depth * 0.2,
    ];
    const cut = holding
      ? [
          [0, 0.14],
          [0.04, 0.1],
          [0.04, 0],
          [0.36, 0],
          [0.43, 0.1],
          [0.96, 0.1],
          [1, 0.15],
          [1, 0.96],
          [0.96, 1],
          [0.04, 1],
          [0, 0.96],
        ]
      : [
          [0, 0.06],
          [0.04, 0],
          [0.85, 0],
          [1, 0.17],
          [1, 0.96],
          [0.96, 1],
          [0.04, 1],
          [0, 0.96],
        ];
    const outline = cut.map(([i, j]) => at(i, j));
    ctx.save();
    ctx.globalAlpha *= opacity;
    face(
      outline.map(([a, b, c]) => [a + 0.025, b - 0.025, c - 0.02]),
      m.side,
      null,
    );
    face(
      outline,
      gradient(projectPoint(at(0, 0)), projectPoint(at(1, 1)), [
        [0, tri || holding ? m.top : m.paper],
        [0.75, tri || holding ? m.mid : m.paper],
        [1, m.top],
      ]),
      tint(m.accent, 0.95),
      0.9,
    );
    onSurface(at(0, 0), at(1, 0), at(0, 1), 180, 116, () => {
      if (tri) {
        rr(48, 26, 80, 61, 13, "#bd4145");
        ctx.fillStyle = "#fff5ee";
        screenPath(
          [
            [77, 39],
            [77, 75],
            [104, 57],
          ],
          true,
        );
        ctx.fill();
        if (!chosen.youtube) {
          ctx.strokeStyle = "#703641";
          ctx.lineWidth = 4;
          ctx.beginPath();
          ctx.arc(148, 77, 7, Math.PI, TAU);
          ctx.stroke();
          rr(136, 77, 24, 18, 3, "#703641");
          rr(146, 82, 4, 8, 2, "#ffd0bc");
        }
      } else if (holding) {
        if (chosen.shared) {
          for (const [x, y, h] of [
            [49, 63, 24],
            [76, 50, 37],
            [103, 37, 50],
          ])
            rr(x, y, 17, h, 3, "#dce8ff");
        }
      } else if (reply) {
        brandMark(kind, 33, 32, a ? 26 : 32);
        if (a) {
          // Identical share stacks sit underneath the falling quote line.
          ctx.strokeStyle = "#8d4954";
          ctx.lineWidth = 6;
          ctx.lineJoin = "round";
          screenPath([
            [56, 29],
            [76, 27],
            [91, 43],
            [106, 39],
            [140, 60],
          ]);
          ctx.stroke();
          for (const x of [57, 110]) {
            rr(x, 75, 32, 5, 2, m.side);
            rr(x, 66, 32, 5, 2, m.side);
          }
        } else {
          // A loupe over the issuer note depicts the independent fact check.
          rr(75, 30, 55, 46, 4, "#e0ebff", "#6285bb");
          ctx.strokeStyle = "#819bc5";
          ctx.lineWidth = 3;
          for (const y of [40, 48]) {
            screenPath([
              [84, y],
              [119, y],
            ]);
            ctx.stroke();
          }
          ctx.strokeStyle = "#0058c9";
          ctx.lineWidth = 5;
          ctx.beginPath();
          ctx.arc(110, 65, 15, 0, TAU);
          ctx.stroke();
          screenPath([
            [121, 76],
            [139, 91],
          ]);
          ctx.stroke();
        }
        ctx.strokeStyle = m.narrow;
        ctx.lineWidth = 1.8;
        ctx.beginPath();
        ctx.moveTo(12, 99);
        ctx.bezierCurveTo(32, 104, 33, 91, 40, 96);
        ctx.bezierCurveTo(47, 103, 53, 96, 66, 97);
        ctx.stroke();
      } else if (chosen.shared) {
        ctx.strokeStyle = "#9c4851";
        ctx.lineWidth = 8;
        ctx.lineJoin = "round";
        screenPath([
          [21, 40],
          [49, 25],
          [76, 50],
          [98, 42],
          [145, 82],
        ]);
        ctx.stroke();
        screenPath([
          [123, 80],
          [146, 83],
          [145, 61],
        ]);
        ctx.stroke();
      } else {
        ctx.strokeStyle = m.side;
        ctx.lineWidth = 6;
        ctx.beginPath();
        ctx.arc(87, 48, 13, Math.PI, TAU);
        ctx.stroke();
        rr(66, 48, 42, 31, 6, m.side);
        rr(84, 58, 6, 12, 3, m.paper);
      }
    });
    ctx.restore();
  }
  function safe(open) {
    const [x, , z] = vault,
      m = materials.metal,
      k = materials.dark;
    const w = 2.16,
      h = 2.45,
      d = 1.22,
      base = 0.22,
      front = z + d / 2;
    // Structural walls and a shadowed cavity. Two exposed shelves create a
    // visible boundary between the safe's contents and the agents outside.
    slab(x, 0.035, z, w + 0.05, d + 0.03, 0.17, k);
    slab(x, base, z, w, d, 0.16, m);
    slab(x, base + 0.15, z - d / 2 + 0.08, w, 0.16, h - 0.26, k);
    slab(x - w / 2 + 0.09, base + 0.13, z, 0.18, d, h - 0.25, m);
    slab(x + w / 2 - 0.09, base + 0.13, z, 0.18, d, h - 0.25, m);
    slab(x, base + 1.19, z, w - 0.23, d - 0.12, 0.095, k);
    sheet(x, 0.43, front - 0.16, 1.43, 0.68, "youtube", { tilt: 0.16 });
    sheet(x, 1.58, front - 0.17, 1.42, 0.69, "holdings", { tilt: 0.2 });
    slab(x, base + h - 0.13, z, w, d, 0.15, m);
    // Door rotates about its left hinge. Its wheel is modelled on both
    // visible planes: the exterior handle and interior radial locking bars.
    const hinge = x - w / 2 + 0.02,
      ang = 0.025 + open * 1.98,
      cs = Math.cos(ang),
      sn = Math.sin(ang);
    const at = (u, y, n = 0) => [hinge + u * cs - n * sn, y, front + 0.08 + u * sn + n * cs];
    const wd = w - 0.055,
      lo = base + 0.08,
      hi = base + h - 0.04;
    const rect = (inset, n) => [
      at(inset, lo + inset, n),
      at(wd - inset, lo + inset, n),
      at(wd - inset, hi - inset, n),
      at(inset, hi - inset, n),
    ];
    const sides = [rect(0, 0.07), rect(0, -0.08)];
    for (let i = 0; i < 4; i++)
      face(
        [sides[0][i], sides[0][(i + 1) % 4], sides[1][(i + 1) % 4], sides[1][i]],
        m.mid,
        tint(m.accent, 0.74),
        0.8,
      );
    const facing = -sn * -sa + cs * ca,
      side = facing >= 0 ? 1 : -1;
    const outer = rect(0, 0.081 * side);
    face(
      outer,
      gradient(projectPoint(outer[2]), projectPoint(outer[0]), [
        [0, m.top],
        [0.43, m.mid],
        [1, m.side],
      ]),
      tint(m.accent, 0.95),
      1.4,
    );
    face(rect(0.12, 0.086 * side), null, tint(m.accent, 0.7), 1.15);
    const wheel = (a, r, n = 0.115 * side) =>
      at(wd * 0.52 + Math.cos(a) * r, base + 1.19 + Math.sin(a) * r, n);
    const ring = Array.from({ length: 45 }, (_, i) => wheel((i * TAU) / 44, 0.43));
    face(ring, "rgba(33,46,67,.68)", m.paper, Math.max(1.6, scale * 0.058));
    for (let j = 0; j < 5; j++) {
      const angle = (j * TAU) / 5 + open * 1.65;
      tube(wheel(angle, 0.065), wheel(angle, 0.41), m.paper, 0.045);
    }
    const c = wheel(0, 0, 0.17 * side);
    pearl(...c, 0.107, 0.105, m.side, m.paper);
    for (const a of [0.34, 1.49]) slab(hinge, a + base, front + 0.08, 0.155, 0.18, 0.34, k);
    for (const v of [0.2, wd - 0.2])
      for (const b of [lo + 0.2, hi - 0.2]) {
        const p = at(v, b, 0.1 * side);
        pearl(...p, 0.045, 0.045, m.mid, m.paper);
      }
  }
  function postTask() {
    const [x, , z] = task,
      k = materials.dark;
    slab(x, 0.035, z, 1.5, 0.87, 0.12, k);
    slab(x, 0.16, z, 0.16, 0.17, 1.13, materials.metal);
    sheet(x, 0.91, z, 1.64, 1.16, "task", { tilt: 0.13, angle: -0.02 });
    slab(x, 2.04, z - 0.12, 0.48, 0.13, 0.07, k);
  }
  function drawDesk() {
    const [x, , z] = desk,
      m = materials.wood,
      k = materials.dark;
    for (const dx of [-1.16, 1.16])
      for (const dz of [-0.59, 0.59]) slab(x + dx, 0.035, z + dz, 0.12, 0.13, 0.96, k);
    tube([x - 1.16, 0.34, z - 0.6], [x + 1.16, 0.34, z - 0.6], k.mid, 0.072);
    slab(x + 0.7, 0.66, z - 0.27, 0.77, 0.71, 0.23, m);
    slab(x, 0.91, z, 2.85, 1.77, 0.13, m);
    // An open task folio serves as a physical landing spot for signed sheets.
    const y = 1.055;
    face(
      [
        [x - 1.06, y, z - 0.24],
        [x + 0.84, y, z - 0.24],
        [x + 0.84, y, z + 0.58],
        [x - 1.06, y, z + 0.58],
      ],
      "#e2cda6",
      "#f5e2b9",
      0.9,
    );
    line(
      [
        [x - 0.13, y + 0.004, z - 0.23],
        [x - 0.13, y + 0.004, z + 0.57],
      ],
      "#a78c72",
      1.4,
    );
    face(
      [
        [x + 0.04, y, z - 0.24],
        [x + 0.1, y, z - 0.44],
        [x + 0.75, y, z - 0.44],
        [x + 0.81, y, z - 0.24],
      ],
      "#dfc092",
      "#f0d9b0",
      0.75,
    );
    // Spiral notebook and pencil identify the human's working surface.
    slab(x - 0.53, 1.045, z - 0.52, 0.85, 0.38, 0.055, materials.source, "paper");
    for (let i = 0; i < 5; i++)
      tube(
        [x - 0.85 + i * 0.14, 1.11, z - 0.67],
        [x - 0.85 + i * 0.14, 1.11, z - 0.6],
        k.ink,
        0.021,
      );
    tube([x + 0.82, 1.076, z + 0.66], [x + 1.18, 1.076, z + 0.32], "#e4aa55", 0.041);
    tube([x + 1.18, 1.076, z + 0.32], [x + 1.24, 1.076, z + 0.27], k.shadow, 0.022);
    // An articulated brass lamp with a lit reflector above the page.
    const lx = x + 1.05,
      lz = z - 0.48;
    slab(lx, 1.05, lz, 0.46, 0.35, 0.065, k);
    tube([lx, 1.11, lz], [lx + 0.05, 1.78, lz], k.side, 0.085, m.top);
    tube([lx + 0.05, 1.78, lz], [lx - 0.28, 1.98, lz], m.side, 0.07, m.top);
    pearl(lx + 0.05, 1.77, lz, 0.07, 0.07, k.mid, m.paper);
    const cap = [lx - 0.31, 1.96, lz],
      base = [lx - 0.39, 1.76, lz + 0.012];
    const rim = Array.from({ length: 25 }, (_, i) => [
      base[0] + 0.27 * Math.cos((i * TAU) / 24),
      base[1] - 0.07 * Math.cos((i * TAU) / 24),
      base[2] + 0.21 * Math.sin((i * TAU) / 24),
    ]);
    for (let i = 0; i < 24; i++) face([cap, rim[i], rim[i + 1]], i > 11 ? "#ad8560" : "#e0ab77");
    face(rim, "#ffe5a6", "#efc08c", 1.2);
    pearl(base[0], base[1] - 0.035, base[2], 0.075, 0.045, "#fff5ce", "#fffaf0");
  }
  const cast = {
    chatgpt: {
      home: [1.0, -1.05],
      pick: [0.31, -1.22],
      consult: [-1.5, 0.16],
      work: [0.88, -1.08],
      deliver: [1.75, -0.78],
      land: [2.4, 0.53],
      offset: 0,
    },
    muse: {
      home: [-1.07, 1.56],
      pick: [-1.48, -0.08],
      consult: [-3.99, 1.25],
      work: [-1.08, 1.51],
      deliver: [3.07, 1.65],
      land: [3.26, 0.47],
      offset: 0.024,
    },
  };
  function actorState(id) {
    const a = cast[id],
      t = phase - a.offset,
      on = chosen[id] && chosen.shared;
    const route = [
      [0, a.home],
      [0.02, a.home],
      [0.15, a.pick],
      [0.22, a.pick],
      [0.375, a.consult],
      [0.46, a.consult],
      [0.58, a.work],
      [0.69, a.work],
      [0.81, a.deliver],
      [0.87, a.deliver],
      [0.975, a.home],
      [1, a.home],
    ];
    let point = a.home,
      speed = 0,
      dir = 0;
    if (on && t >= 0) {
      for (let i = 1; i < route.length; i++) {
        if (t > route[i][0]) continue;
        const [start, p] = route[i - 1],
          [end, q] = route[i],
          u = clamp((t - start) / (end - start)),
          e = wave(u);
        point = [mix(p[0], q[0], e), mix(p[1], q[1], e)];
        speed = Math.min(1, Math.hypot(q[0] - p[0], q[1] - p[1])) * Math.sin(u * Math.PI);
        dir = Math.sign(q[0] - p[0]) * speed;
        break;
      }
    }
    return { id, a, on, t, x: point[0], z: point[1], speed, dir };
  }
  function robot(actor) {
    const { id, a, t, on, x, z, speed, dir } = actor,
      m = materials[id],
      isGPT = id === "chatgpt";
    const stride = Math.sin((phase + (isGPT ? 0 : 0.38)) * TAU * 21) * speed,
      bob = Math.abs(stride) * 0.095;
    const height = isGPT ? 1 : 0.91,
      work = on && t >= 0.46 && t <= 0.7;
    const f = (u, v, d) => [x + u * height, (v + bob) * height, z + d * height];
    const ball = (u, v, d, rx, ry, c, shine, e) =>
      pearl(...f(u, v, d), rx * height, ry * height, c, shine, e);
    // Alternating offset knees and shoes read as an actual walk.
    for (const side of [-1, 1]) {
      const shift = side * stride * 0.15;
      const foot = f(
        side * 0.24 + shift,
        0.115 + Math.max(0, side * stride) * 0.08,
        0.035 + 0.085 * side * stride,
      );
      tube(
        f(side * 0.195, 0.58, 0),
        f(side * 0.21 + shift * 0.5, 0.34, 0.055),
        m.shadow,
        0.12,
        m.mid,
      );
      tube(f(side * 0.21 + shift * 0.5, 0.34, 0.055), foot, m.side, 0.105, m.top);
      pearl(...foot, 0.235 * height, 0.105 * height, m.mid, m.paper, m.shadow);
    }
    ball(0, 0.68, 0, 0.355, 0.364, m.mid, m.paper, m.shadow);
    // Front service hatch and a pair of indicator lights.
    ball(0.012, 0.71, 0.19, 0.19, 0.13, m.side, m.top, m.shadow);
    ball(-0.034, 0.73, 0.24, 0.038, 0.032, isGPT ? "#fcfcfc" : "#cbe7ff", "#ffffff");
    const pickup = 0.5 + 0.5 * Math.sin(phase * TAU * 5);
    const handL = f(-0.39, 0.65 + -stride * 0.14, 0.11),
      handR = f(0.46, work ? 0.86 + pickup * 0.07 : 0.67 + stride * 0.06, 0.14);
    for (const [side, hand] of [
      [-1, handL],
      [1, handR],
    ]) {
      const shoulder = f(side * 0.28, 0.9, 0.02),
        elbow = f(side * 0.43, 0.73, 0.03);
      tube(shoulder, elbow, m.side, 0.13, m.top);
      tube(elbow, hand, m.mid, 0.105, m.top);
      pearl(...elbow, 0.078, 0.077, m.side, m.paper);
      pearl(...hand, 0.099, 0.091, m.top, m.paper, m.mid);
    }
    if (on && t >= 0.15 && t < 0.845) {
      const take = wave((t - 0.15) / 0.055);
      const hold = f(0.43, 0.6 + 0.045 * pickup, 0.3);
      const carrying = [
        mix(task[0], hold[0], take),
        mix(1.18, hold[1], take),
        mix(task[2] + 0.12, hold[2], take),
      ];
      const read = wave((t - 0.385) / 0.07),
        signed = clamp((t - 0.63) / 0.055),
        report = signed > 0.5;
      // Both copies leave the same posted task. Each robot then tucks the
      // selected source cards behind its copy when it reaches the safe.
      const size = mix(0.86, 0.63, take);
      if (read > 0 && !report) {
        const shelf = [vault[0], vault[2] + 0.48];
        sheet(
          mix(shelf[0], carrying[0] - 0.09, read),
          mix(1.58, carrying[1] + 0.1, read),
          mix(shelf[1], carrying[2] - 0.04, read),
          size,
          0.42,
          "holdings",
          { tilt: 0.19, opacity: read },
        );
        if (chosen.youtube)
          sheet(
            mix(shelf[0], carrying[0] + 0.09, read),
            mix(0.43, carrying[1] + 0.14, read),
            mix(shelf[1], carrying[2] - 0.02, read),
            size * 0.73,
            0.37,
            "youtube",
            { tilt: 0.2, opacity: read },
          );
      }
      const land = wave((t - 0.805) / 0.04);
      const px = mix(carrying[0], a.land[0], land),
        py = mix(carrying[1], 1.085, land),
        pz = mix(carrying[2], a.land[1], land);
      sheet(px, py, pz, mix(size, 0.85, land), mix(0.49, 0.65, land), report ? id : "task", {
        tilt: mix(0.12, 1.32, land),
        angle: mix(-0.13, isGPT ? -0.055 : 0.08, land),
      });
    }
    tube(f(0, 0.98, 0), f(0, 1.13, 0), m.shadow, 0.14, m.top);
    // The provider faceplate sits in a rounded enamelled shell. Its ear
    // joints and antenna sit in front of and behind it at different depths.
    const lift = work ? 0.025 * Math.sin(phase * TAU * 4) : 0;
    const c = f(dir * 0.065, 1.36 + lift, 0.025),
      head = projectPoint(c);
    const hw = (isGPT ? 0.5 : 0.46) * height * scale,
      hh = (isGPT ? 0.33 : 0.355) * height * scale;
    ball(-0.49, 1.35, 0, 0.119, 0.15, m.mid, m.paper, m.shadow);
    ball(0.49, 1.35, 0, 0.116, 0.15, m.mid, m.paper, m.shadow);
    if (isGPT) {
      tube(f(-0.12, 1.61, 0), f(-0.16, 1.85, 0), m.side, 0.041, m.top);
      ball(-0.16, 1.88, 0, 0.076, 0.081, m.top, m.paper, m.mid);
    } else {
      for (const side of [-1, 1]) {
        tube(f(side * 0.29, 1.62, 0), f(side * 0.39, 1.82, 0.015), m.mid, 0.068, m.paper);
        ball(side * 0.39, 1.83, 0.015, 0.075, 0.084, m.top, m.paper, m.mid);
      }
    }
    ctx.save();
    ctx.translate(head[0], head[1]);
    ctx.rotate(stride * 0.034 + (work ? 0.055 : 0));
    ctx.scale(hw / 50, hh / 32);
    const shell = ctx.createLinearGradient(-42, -32, 40, 29);
    shell.addColorStop(0, m.paper);
    shell.addColorStop(0.18, m.top);
    shell.addColorStop(0.64, m.mid);
    shell.addColorStop(1, m.side);
    rr(-50, -32, 100, 64, isGPT ? 24 : 29, shell, m.top);
    rr(
      -41,
      -25,
      82,
      50,
      isGPT ? 16 : 22,
      isGPT ? "#17181a" : "#fafcff",
      isGPT ? "#a9aeb3" : "#d3e5ff",
    );
    // Uniform scaling preserves each outline independently of the head shape.
    ctx.scale(1, hw / 50 / (hh / 32));
    brandMark(id, 0, 0, isGPT ? 39 : 57, "#ffffff");
    ctx.restore();
  }
  function notebookReport(id) {
    const a = cast[id],
      t = phase - a.offset;
    const show = chosen.shared && chosen[id] && (t >= 0.845 || (completedLoop && t < 0.12));
    if (!show) return;
    const alpha = t >= 0.845 ? 1 : 1 - wave((t - 0.075) / 0.045);
    sheet(a.land[0], 1.085, a.land[1], 0.85, 0.65, id, {
      tilt: 1.32,
      angle: id === "chatgpt" ? -0.055 : 0.08,
      opacity: alpha,
    });
  }
  // Only draw short footprints between stations. They indicate motion without
  // turning the entire scene into a diagram of glowing wires.
  function footprints(actor) {
    if (!actor.on || actor.speed < 0.2) return;
    const m = materials[actor.id],
      direction = actor.dir < 0 ? -1 : 1;
    for (let i = 1; i < 4; i++) {
      const p = project(actor.x - i * 0.17 * direction, 0.02, actor.z + (i % 2 ? 0.12 : -0.12));
      ctx.fillStyle = tint(m.accent, (1 - i / 4) * 0.38);
      ctx.beginPath();
      ctx.ellipse(
        p[0],
        p[1],
        Math.max(1, 0.07 * scale),
        Math.max(0.7, 0.027 * scale),
        0.25,
        0,
        TAU,
      );
      ctx.fill();
    }
  }
  function render() {
    if (!ctx || cw < 5 || ch < 5) return;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, cw, ch);
    ca = Math.cos(camera[3]);
    sa = Math.sin(camera[3]);
    ce = Math.cos(camera[4]);
    se = Math.sin(camera[4]);
    scale = Math.min(cw / camera[5], ch / camera[6]);
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    stageFloor();
    const actors = Object.keys(cast).map(actorState);
    const open =
      chosen.shared && (chosen.chatgpt || chosen.muse)
        ? wave((phase - 0.09) / 0.2) * (1 - wave((phase - 0.7) / 0.22))
        : 0.08;
    shadow(vault[0], vault[2], 1.65, 1.21, 0.55);
    shadow(task[0], task[2], 1.04, 0.62, 0.4);
    shadow(desk[0], desk[2], 1.95, 1.32, 0.5);
    for (const a of actors) {
      shadow(a.x, a.z, 0.65, 0.4, 0.52);
      footprints(a);
    }
    const objects = [
      { p: [vault[0], 1.02, vault[2]], draw: () => safe(open) },
      { p: [task[0], 0.88, task[2]], draw: postTask },
      {
        p: [desk[0], 0.69, desk[2]],
        draw: () => {
          drawDesk();
          notebookReport("chatgpt");
          notebookReport("muse");
        },
      },
      ...actors.map((a) => ({ p: [a.x, 0.81, a.z], draw: () => robot(a) })),
    ];
    objects.sort((a, b) => projectPoint(a.p)[2] - projectPoint(b.p)[2]).forEach((o) => o.draw());
  }
  function tick(now) {
    frame = 0;
    if (paused || !visible || document.hidden || reduceMotion.matches) return;
    if (last && now - last < 29) {
      frame = requestAnimationFrame(tick);
      return;
    }
    const dt = last ? Math.min((now - last) / 1000, 0.1) : 0;
    last = now;
    drift += dt;
    const next = phase + dt / 8.8;
    if (next >= 1) completedLoop = true;
    phase = next % 1;
    const target = shots[active],
      amount = 1 - Math.exp(-dt * 4.7);
    for (let i = 0; i < camera.length; i++)
      camera[i] = mix(
        camera[i],
        target[i] + (i === 3 ? 0.016 * Math.sin(drift * 0.55) : 0),
        amount,
      );
    render();
    frame = requestAnimationFrame(tick);
  }
  function animate() {
    cancelAnimationFrame(frame);
    last = 0;
    frame = 0;
    render();
    if (ctx && visible && !paused && !reduceMotion.matches && !document.hidden)
      frame = requestAnimationFrame(tick);
  }
  function resize() {
    const rect = stage.getBoundingClientRect();
    cw = Math.max(1, rect.width);
    ch = Math.max(1, rect.height);
    ratio = Math.min(devicePixelRatio || 1, 1.75);
    canvas.width = Math.round(cw * ratio);
    canvas.height = Math.round(ch * ratio);
    render();
  }
  function describe() {
    const w = studio[language],
      l = labels[language];
    const agents = Object.keys(cast).filter((id) => chosen[id]);
    const names = { chatgpt: "ChatGPT", muse: "Muse" };
    const reports = agents.map((id) => names[id] + " — " + l[id].finding);
    let text;
    if (!chosen.shared) text = w.none;
    else if (!agents.length) text = w.unassigned;
    else {
      const instruction =
        agents.length === 1 ? l.single.replace("{agent}", names[agents[0]]) : w.scenes[active];
      const findings = active === 3 || agents.length === 1 ? reports : [];
      text = [
        l.snapshot,
        l.fullQuestion,
        instruction,
        ...findings,
        chosen.youtube ? w.context : w.only,
      ].join(" ");
    }
    stage.setAttribute("aria-label", text);
    if (!ctx) {
      const fallback = document.createElement("div");
      fallback.className = "flow-fallback";
      const signed = agents.map((id) => names[id] + " · " + l[id].title);
      const items =
        chosen.shared && agents.length
          ? [
              l.example + " · " + l.change,
              l.fullQuestion,
              active === 3
                ? signed.join(" / ")
                : agents.map((id) => names[id]).join(" + ") + " → " + w.desk,
            ]
          : [w.library, text];
      for (const item of items) {
        const el = document.createElement("span");
        el.textContent = item;
        fallback.append(el);
      }
      stage.replaceChildren(fallback);
    }
  }
  stage.setAttribute("role", "img");
  window.FolioFlow = {
    show(index) {
      if (!Number.isInteger(index) || index < 0 || index >= shots.length || index === active)
        return;
      active = index;
      // Changing chapters only moves the camera. Robots keep the same continuous
      // position and the common timeline; static frames select a readable moment.
      if (paused || reduceMotion.matches) {
        camera.splice(0, camera.length, ...shots[active]);
        phase = stillPhases[active];
      }
      describe();
      animate();
    },
    setPaused(value) {
      if (paused === Boolean(value)) return;
      paused = Boolean(value);
      animate();
    },
    setLanguage(value) {
      if (!Object.hasOwn(studio, value)) return;
      language = value;
      describe();
      render();
    },
    setRecipients(values = {}) {
      for (const key of Object.keys(chosen))
        if (typeof values[key] === "boolean") chosen[key] = values[key];
      describe();
      render();
    },
  };
  if (ctx) {
    new ResizeObserver(resize).observe(stage);
    new IntersectionObserver((entries) => {
      visible = !!entries[0]?.isIntersecting;
      animate();
    }).observe(stage);
    lightMode.addEventListener("change", () => {
      light = lightMode.matches;
      render();
    });
    reduceMotion.addEventListener("change", () => {
      if (reduceMotion.matches) {
        camera.splice(0, camera.length, ...shots[active]);
        phase = stillPhases[active];
      }
      animate();
    });
    document.addEventListener("visibilitychange", animate);
    if (reduceMotion.matches) phase = stillPhases[0];
    resize();
    animate();
  }
  describe();
})();
