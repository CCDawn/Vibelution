/**
 * Generate double-click standalone teams shell preview (B&W).
 * Left: team list. Right: full team content with canvas | board modes.
 */
const fs = require("fs");
const path = require("path");

const css = fs.readFileSync(
  path.join(__dirname, "../src/design/research-overview-preview.css"),
  "utf8",
);

const js = String.raw`
const TEAMS = [
  {
    id: "challenge-cup",
    name: "挑战杯科研",
    kind: "科研工作流",
    members: 12,
    status: "活跃",
    blurb: "三阶段：知识搜集 → 实验设计 → 执行迭代",
    purpose: "挑战杯 AI 科研团队 · 项目推进与阶段协作",
  },
  {
    id: "ai-search",
    name: "AI 搜索范围",
    kind: "资料范围",
    members: 4,
    status: "活跃",
    blurb: "跨源检索与资料准入",
    purpose: "配置搜索范围、来源策略与准入边界",
  },
  {
    id: "knowledge-expand",
    name: "知识扩充",
    kind: "扩充工作流",
    members: 5,
    status: "待命",
    blurb: "既有知识库的补充与关系扩展",
    purpose: "在既有知识基础上做补充搜集与结构化",
  },
  {
    id: "example-collab",
    name: "示例协作组",
    kind: "示例",
    members: 3,
    status: "示例",
    blurb: "用于演示空团队与引导态",
    purpose: "演示未配置工作流时的空白态",
  },
];

const CANVAS_NODES = {
  "challenge-cup": [
    { id: "lead", label: "科研协调", role: "Lead", tone: "lead", x: 48, y: 40, status: "在线" },
    { id: "finder", label: "白书遥", role: "资料寻找", tone: "active", x: 280, y: 36, status: "等待任务" },
    { id: "extract", label: "白望舒", role: "资料提炼", tone: "active", x: 500, y: 36, status: "可用" },
    { id: "relation", label: "顾言初", role: "关系整理", tone: "idle", x: 280, y: 180, status: "待命" },
    { id: "ingest", label: "林知序", role: "资料入库", tone: "idle", x: 500, y: 180, status: "待命" },
    { id: "exp", label: "沈观止", role: "实验规划", tone: "active", x: 720, y: 100, status: "进行中" },
    { id: "iter", label: "周衡", role: "执行调度", tone: "idle", x: 940, y: 100, status: "待命" },
  ],
  "ai-search": [
    { id: "lead", label: "范围协调", role: "Lead", tone: "lead", x: 80, y: 80, status: "在线" },
    { id: "web", label: "网页检索", role: "Web", tone: "active", x: 320, y: 60, status: "可用" },
    { id: "local", label: "本地扫描", role: "Local", tone: "idle", x: 320, y: 200, status: "待命" },
    { id: "gate", label: "准入门禁", role: "Gate", tone: "active", x: 560, y: 120, status: "运行" },
  ],
  "knowledge-expand": [
    { id: "lead", label: "扩充协调", role: "Lead", tone: "lead", x: 100, y: 100, status: "在线" },
    { id: "a", label: "补充搜集", role: "Expand", tone: "active", x: 340, y: 80, status: "进行中" },
    { id: "b", label: "关系扩展", role: "Graph", tone: "idle", x: 340, y: 220, status: "待命" },
  ],
  "example-collab": [
    { id: "lead", label: "示例 Lead", role: "Lead", tone: "lead", x: 120, y: 120, status: "示例" },
    { id: "m1", label: "成员 A", role: "Member", tone: "idle", x: 360, y: 90, status: "—" },
    { id: "m2", label: "成员 B", role: "Member", tone: "idle", x: 360, y: 220, status: "—" },
  ],
};

const BOARD = {
  "challenge-cup": {
    projectName: "三阶段验收 | 稀疏预测误差门控假说",
    topic: "新假说：在相同数据、固定 seed=42 下，稀疏预测误差门控可降低 reconstruction_mse。",
    nextTitle: "进入实验设计",
    nextBody: "资料阶段已有轮次。建议进入实验设计，将证据收敛为可证伪假设与冻结协议。",
    cta: "进入实验设计",
    metrics: [
      { label: "阶段", value: "知识搜集 → 实验" },
      { label: "资料批次", value: "2" },
      { label: "候选", value: "17" },
    ],
    handoff: "知识搜集 → 实验设计 · 证据已形成可用假设",
    columns: [
      {
        id: "kc",
        title: "知识搜集",
        cards: [
          {
            title: "层级机制证据补齐",
            body: "16 条资料 · 提炼中 · 来源可追溯",
            meta: ["批次 #2", "候选 17"],
            foot: "进行中",
            active: false,
          },
          {
            title: "可塑性规则检索",
            body: "8 条资料 · 已暂停",
            meta: ["草稿"],
            foot: "暂停",
            active: false,
          },
        ],
      },
      {
        id: "ex",
        title: "实验设计",
        cards: [
          {
            title: "Design v4 · 冻结基线",
            body: "weight=0.875 · 5 seeds · formal · 可执行",
            meta: ["冻结", "可执行"],
            foot: "当前主线",
            active: true,
          },
          {
            title: "Design v5-diagnostic",
            body: "alignment × mask · 待审查",
            meta: ["修订"],
            foot: "待审查",
            active: false,
          },
        ],
      },
      {
        id: "it",
        title: "执行与迭代",
        cards: [
          {
            title: "formal-v4",
            body: "通过门禁 · +2.8% · 5 seeds",
            meta: ["通过", "最佳"],
            foot: "已晋升",
            active: false,
          },
          {
            title: "smoke_needs_review",
            body: "诊断 run · 不覆盖主线结果",
            meta: ["诊断"],
            foot: "待审查",
            active: false,
          },
        ],
      },
    ],
  },
  "ai-search": {
    projectName: "AI 搜索范围配置",
    topic: "定义允许的检索源、本地根目录与写入边界。",
    nextTitle: "继续配置搜索范围",
    nextBody: "先确认 web / local 源与准入门禁，再发起范围校验。",
    cta: "打开范围配置",
    metrics: [
      { label: "源", value: "web + local" },
      { label: "门禁", value: "2 / 3" },
      { label: "成员", value: "4" },
    ],
    handoff: null,
    columns: [
      {
        id: "scope",
        title: "范围",
        cards: [
          { title: "Web 检索策略", body: "英文优先 · DOI 优先", meta: ["web"], foot: "已配置", active: true },
          { title: "本地扫描根", body: "Documents/Research", meta: ["local"], foot: "已绑定", active: false },
        ],
      },
      {
        id: "gate",
        title: "门禁",
        cards: [
          { title: "来源可追溯", body: "URL / 路径必须可回放", meta: ["必选"], foot: "通过", active: false },
          { title: "写入边界", body: "禁止直接写正式知识库", meta: ["边界"], foot: "生效", active: false },
        ],
      },
      {
        id: "run",
        title: "运行",
        cards: [
          { title: "最近校验", body: "通过 18 · 拒绝 2", meta: ["校验"], foot: "今天 09:20", active: false },
        ],
      },
    ],
  },
  "knowledge-expand": {
    projectName: "知识扩充主线",
    topic: "在既有条目上补充缺口证据与关系边。",
    nextTitle: "继续知识扩充",
    nextBody: "先补齐缺口 Claim，再扩展关系图。",
    cta: "进入扩充",
    metrics: [
      { label: "缺口", value: "5" },
      { label: "新边", value: "12" },
      { label: "成员", value: "5" },
    ],
    handoff: null,
    columns: [
      {
        id: "gap",
        title: "缺口",
        cards: [
          { title: "参数区间 Claim", body: "邻域结果不稳定", meta: ["claim"], foot: "待补证", active: true },
        ],
      },
      {
        id: "expand",
        title: "扩充中",
        cards: [
          { title: "补充检索批次", body: "3 条新候选", meta: ["batch"], foot: "进行中", active: false },
        ],
      },
      {
        id: "graph",
        title: "关系",
        cards: [
          { title: "关系扩展草稿", body: "12 条候选边待审", meta: ["graph"], foot: "草稿", active: false },
        ],
      },
    ],
  },
  "example-collab": {
    projectName: "示例协作组",
    topic: "尚未绑定正式工作流。选择或初始化后可进入画布与看板。",
    nextTitle: "初始化示例工作流",
    nextBody: "当前仅用于演示布局。生产环境请选择科研或搜索团队。",
    cta: "查看引导",
    metrics: [
      { label: "成员", value: "3" },
      { label: "工作流", value: "—" },
      { label: "状态", value: "示例" },
    ],
    handoff: null,
    columns: [
      { id: "todo", title: "待办", cards: [{ title: "绑定工作流类型", body: "选择科研 / 搜索 / 扩充", meta: ["setup"], foot: "未开始", active: true }] },
      { id: "doing", title: "进行中", cards: [] },
      { id: "done", title: "完成", cards: [] },
    ],
  },
};

const params = new URLSearchParams(location.search || "");
let selectedTeamId = params.get("team") || "challenge-cup";
let mode = params.get("mode") === "canvas" ? "canvas" : "board"; // board | canvas
let advancedOpen = false;
let toastTimer = null;
let teamFilter = "";

function el(tag, attrs, children) {
  const node = document.createElement(tag);
  if (attrs) {
    Object.entries(attrs).forEach(([k, v]) => {
      if (v == null || v === false) return;
      if (k === "className") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k === "html") node.innerHTML = v;
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
      else node.setAttribute(k, v === true ? "" : String(v));
    });
  }
  (children || []).forEach((c) => {
    if (c == null || c === false) return;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  });
  return node;
}

function showToast(msg) {
  const existing = document.querySelector(".toast");
  if (existing) existing.remove();
  const t = el("div", { className: "toast", role: "status", text: msg });
  document.body.appendChild(t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.remove(), 2200);
}

function selectedTeam() {
  return TEAMS.find((t) => t.id === selectedTeamId) || TEAMS[0];
}

function renderCanvas(teamId) {
  const nodes = CANVAS_NODES[teamId] || [];
  const board = el("div", { className: "canvas-board", "aria-label": "团队组织画布" });
  board.appendChild(el("div", { className: "canvas-hint", text: "画布模式 · 组织关系与 Agent 节点（只读预览）" }));

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "canvas-edge-layer");
  svg.setAttribute("viewBox", "0 0 1200 360");
  svg.setAttribute("preserveAspectRatio", "none");
  // simple chain edges
  for (let i = 0; i < nodes.length - 1; i++) {
    const a = nodes[i];
    const b = nodes[i + 1];
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    const x1 = a.x + 84;
    const y1 = a.y + 44;
    const x2 = b.x + 84;
    const y2 = b.y + 44;
    const mx = (x1 + x2) / 2;
    path.setAttribute("d", "M " + x1 + " " + y1 + " C " + mx + " " + y1 + ", " + mx + " " + y2 + ", " + x2 + " " + y2);
    svg.appendChild(path);
  }
  board.appendChild(svg);

  nodes.forEach((n) => {
    board.appendChild(
      el("article", {
        className: "canvas-node",
        "data-tone": n.tone,
        style: { left: n.x + "px", top: n.y + "px" },
        onClick: () => showToast("画布节点：" + n.label + " · " + n.role),
      }, [
        el("strong", { text: n.label }),
        el("span", { text: n.role }),
        el("em", { text: n.status }),
      ]),
    );
  });
  return board;
}

function renderBoard(teamId) {
  const data = BOARD[teamId];
  if (!data) {
    return el("div", { className: "workspace-empty" }, [
      el("strong", { text: "暂无看板数据" }),
      el("span", { text: "请选择其他团队" }),
    ]);
  }

  const hero = el("section", { className: "next-card" }, [
    el("div", { className: "next-card-top" }, [
      el("span", { className: "next-badge", text: "下一步" }),
      el("span", { text: "·" }),
      el("span", { text: data.projectName }),
    ]),
    el("h2", { text: data.nextTitle }),
    el("p", { text: data.nextBody }),
    data.handoff
      ? el("div", { className: "handoff-banner", role: "status" }, [
          el("strong", { text: "阶段交接" }),
          el("span", { text: data.handoff }),
        ])
      : null,
    el("div", { className: "metric-row" }, data.metrics.map((m) =>
      el("div", { className: "metric" }, [el("span", { text: m.label }), el("strong", { text: m.value })],
    ))),
    el("div", { className: "next-card-actions" }, [
      el("button", {
        type: "button",
        className: "btn btn-primary",
        text: data.cta + " →",
        onClick: () => showToast("主 CTA：" + data.cta),
      }),
    ]),
  ].filter(Boolean));

  const kanban = el("section", { className: "kanban", "aria-label": "看板" }, data.columns.map((col) =>
    el("div", { className: "kanban-col" }, [
      el("div", { className: "kanban-col-head" }, [
        el("h3", { text: col.title }),
        el("span", { text: String(col.cards.length) }),
      ]),
      ...(col.cards.length
        ? col.cards.map((card) =>
            el("article", {
              className: "kanban-card",
              "data-active": card.active ? "true" : "false",
              onClick: () => showToast("看板卡片：" + card.title),
            }, [
              el("strong", { text: card.title }),
              el("p", { text: card.body }),
              el("div", { className: "kanban-card-meta" }, card.meta.map((m) => el("em", { text: m }))),
              el("div", { className: "kanban-card-foot" }, [
                el("span", { text: card.foot }),
                el("button", {
                  type: "button",
                  className: "btn btn-ghost",
                  text: "查看",
                  onClick: (e) => {
                    e.stopPropagation();
                    showToast("查看：" + card.title);
                  },
                }),
              ]),
            ]),
          )
        : [el("p", { className: "preview-note", text: "本列暂无卡片", style: { textAlign: "left", margin: "4px 0" } })]),
    ]),
  ));

  const advanced = el("section", { className: "advanced" }, [
    el("button", {
      type: "button",
      className: "advanced-toggle",
      "aria-expanded": advancedOpen ? "true" : "false",
      onClick: () => {
        advancedOpen = !advancedOpen;
        render();
      },
    }, [
      el("strong", { text: (advancedOpen ? "▾ " : "▸ ") + "高级详情" }),
      el("span", { text: advancedOpen ? "收起" : "证据与校验" }),
    ]),
    advancedOpen
      ? el("dl", { className: "advanced-panel" }, [
          el("div", { className: "advanced-row" }, [el("dt", { text: "模式" }), el("dd", { text: "看板 · 团队全量内容" })]),
          el("div", { className: "advanced-row" }, [el("dt", { text: "项目" }), el("dd", { text: data.projectName })]),
          el("div", { className: "advanced-row" }, [el("dt", { text: "说明" }), el("dd", { text: "预览页假数据 · 黑白配色 · 可双击打开" })]),
        ])
      : null,
  ]);

  return el("div", { className: "board-overview" }, [
    el("div", { className: "section-label" }, [
      el("h3", { text: "项目推进" }),
      el("span", { text: "看板模式 · 单一主 CTA + 三列阶段" }),
    ]),
    hero,
    el("div", { className: "section-label" }, [
      el("h3", { text: "阶段看板" }),
      el("span", { text: "卡片只读预览 · 点击查看" }),
    ]),
    kanban,
    advanced,
  ]);
}

function render() {
  const team = selectedTeam();
  const root = document.getElementById("root");
  root.innerHTML = "";

  const filtered = TEAMS.filter((t) => {
    if (!teamFilter.trim()) return true;
    const q = teamFilter.trim().toLowerCase();
    return [t.name, t.kind, t.blurb, t.purpose].join(" ").toLowerCase().includes(q);
  });

  const rail = el("aside", { className: "team-rail", "aria-label": "团队列表" }, [
    el("div", { className: "team-rail-head" }, [
      el("h2", { text: "团队" }),
      el("span", { text: TEAMS.length + " 个" }),
    ]),
    el("input", {
      className: "team-search",
      type: "search",
      placeholder: "搜索团队…",
      value: teamFilter,
      "aria-label": "搜索团队",
      onInput: (e) => {
        teamFilter = e.target.value;
        render();
      },
    }),
    el("div", { className: "team-list", role: "listbox", "aria-label": "可选团队" }, filtered.map((t) =>
      el("button", {
        type: "button",
        className: "team-item",
        role: "option",
        "data-active": t.id === selectedTeamId ? "true" : "false",
        "aria-selected": t.id === selectedTeamId ? "true" : "false",
        onClick: () => {
          selectedTeamId = t.id;
          advancedOpen = false;
          render();
          showToast("已选择团队：" + t.name);
        },
      }, [
        el("div", { className: "team-item-title" }, [
          el("span", { text: t.name }),
          el("em", {
            text: t.status,
            style: {
              fontStyle: "normal",
              fontSize: "10px",
              fontWeight: "740",
              padding: "2px 6px",
              borderRadius: "999px",
              border: t.id === selectedTeamId ? "1px solid rgb(255 255 255 / 35%)" : "1px solid var(--line)",
            },
          }),
        ]),
        el("div", { className: "team-item-meta" }, [
          el("span", { text: t.kind }),
          el("span", { text: t.members + " 成员" }),
        ]),
        el("small", { text: t.blurb }),
      ]),
    )),
    el("p", {
      className: "preview-note",
      text: "左侧选团队 → 右侧展示整队内容。模式：看板 / 画布。",
      style: { textAlign: "left", margin: "4px" },
    }),
  ]);

  const toolbar = el("div", { className: "workspace-toolbar" }, [
    el("div", { className: "workspace-identity" }, [
      el("div", { className: "eyebrow", text: "当前团队" }),
      el("h1", { text: team.name }),
      el("p", { text: team.purpose }),
    ]),
    el("div", { className: "workspace-toolbar-actions" }, [
      el("div", { className: "mode-switch", role: "tablist", "aria-label": "展示模式" }, [
        el("button", {
          type: "button",
          role: "tab",
          "data-active": mode === "board" ? "true" : "false",
          "aria-selected": mode === "board" ? "true" : "false",
          text: "看板模式",
          onClick: () => {
            mode = "board";
            render();
          },
        }),
        el("button", {
          type: "button",
          role: "tab",
          "data-active": mode === "canvas" ? "true" : "false",
          "aria-selected": mode === "canvas" ? "true" : "false",
          text: "画布模式",
          onClick: () => {
            mode = "canvas";
            render();
          },
        }),
      ]),
      el("button", {
        type: "button",
        className: "btn",
        text: "研究关系图",
        onClick: () => showToast("打开研究关系图（预览）"),
      }),
    ]),
  ]);

  const body = el(
    "div",
    { className: "workspace-body" },
    [mode === "canvas" ? renderCanvas(team.id) : renderBoard(team.id)],
  );

  const workspace = el("section", { className: "workspace", "aria-label": "团队内容" }, [
    toolbar,
    body,
  ]);

  const app = el("div", { className: "preview-app" }, [
    el("header", { className: "topbar" }, [
      el("div", { className: "topbar-brand" }, [
        el("div", { className: "topbar-mark" }),
        el("div", null, [
          el("strong", { text: "Vibelution" }),
          el("span", { text: "团队工作台 · 黑白预览" }),
        ]),
      ]),
      el("nav", { className: "topbar-nav", "aria-label": "主导航" }, [
        el("button", { type: "button", text: "对话" }),
        el("button", { type: "button", text: "监督进化" }),
        el("button", { type: "button", text: "自进化" }),
        el("button", { type: "button", "data-active": "true", text: "团队" }),
        el("button", { type: "button", text: "Kernel" }),
        el("button", { type: "button", text: "记忆库" }),
      ]),
      el("div", { className: "topbar-meta" }, [
        el("span", { className: "pill" }, [
          el("span", { className: "pill-dot" }),
          document.createTextNode(" 独立页可打开"),
        ]),
        el("span", { text: "v1.0.16" }),
      ]),
    ]),
    el("div", { className: "layout" }, [rail, workspace]),
  ]);

  root.appendChild(app);
}

document.addEventListener("DOMContentLoaded", render);
`;

const html = `<!doctype html>
<html lang="zh-CN" data-theme="light">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>团队工作台 · 画布/看板预览 | Vibelution</title>
  <style>
${css}
  /* standalone overrides: old .rail hidden styles shouldn't block team-rail */
  .team-rail { display: grid !important; }
  .layout { height: calc(100vh - 52px); }
  </style>
</head>
<body>
  <div id="root"></div>
  <script>
${js}
  </script>
</body>
</html>
`;

const outWeb = path.join(__dirname, "../research-overview-preview-standalone.html");
const outDesk = path.join(process.env.USERPROFILE || "", "Desktop", "科研总览预览-双击打开.html");
const outDesk2 = path.join(process.env.USERPROFILE || "", "Desktop", "团队工作台预览-双击打开.html");
fs.writeFileSync(outWeb, html, "utf8");
fs.writeFileSync(outDesk, html, "utf8");
fs.writeFileSync(outDesk2, html, "utf8");
console.log("wrote", outWeb, fs.statSync(outWeb).size);
console.log("wrote", outDesk, fs.statSync(outDesk).size);
console.log("wrote", outDesk2, fs.statSync(outDesk2).size);
