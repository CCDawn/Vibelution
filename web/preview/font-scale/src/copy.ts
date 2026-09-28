/**
 * 预览文案字典：中文为主，EN 切换。只服务本预览页，不进生产。
 */
export type Lang = "zh" | "en";

export const COPY = {
  pageTitle: { zh: "单一字号派生字阶预览", en: "Derived Font Scale Preview" },
  pageSub: {
    zh: "一个 --vui-font-base 基准 + 固定偏移派生全套主字阶；画布/桌宠/终端为固定密度例外",
    en: "One --vui-font-base plus fixed offsets derives the whole main ladder; canvas/pet/terminal stay fixed",
  },
  baseLabel: { zh: "基准字号", en: "Base size" },
  baseUnit: { zh: "px", en: "px" },
  quickLabel: { zh: "快捷档", en: "Quick" },
  abToggle: { zh: "A/B 对拍", en: "A/B compare" },
  abExit: { zh: "退出对拍", en: "Exit A/B" },
  langToggle: { zh: "EN", en: "中文" },
  abLeftTitle: { zh: "基准 16px（现网）", en: "Base 16px (current)" },
  abRightTitle: { zh: "当前所选", en: "Selected" },
  abSameHint: {
    zh: "当前所选即 16px，与左侧相同",
    en: "Selection equals 16px — same as left",
  },

  sectionLadder: { zh: "派生字阶总览", en: "Derived ladder" },
  sectionSettings: { zh: "设置行样张", en: "Settings rows" },
  sectionChat: { zh: "会话样张（md / chat 档）", en: "Conversation (md / chat rungs)" },
  sectionDense: { zh: "密集操作样张", en: "Dense operations" },
  sectionFixed: { zh: "固定例外对照", en: "Fixed exceptions" },
  fixedCaption: {
    zh: "固定密度轴：不随基准缩放（画布 9–15px / 桌宠固定 px / 终端 13px）",
    en: "Fixed density axes: do not scale with base (canvas 9–15px / pet fixed px / terminal 13px)",
  },

  ladderColRung: { zh: "档位", en: "Rung" },
  ladderColValue: { zh: "当前计算值", en: "Computed" },
  ladderColOffset: { zh: "偏移", en: "Offset" },
  ladderColUsage: { zh: "用途", en: "Usage" },

  rowLanguage: { zh: "界面语言", en: "Interface language" },
  rowLanguageDesc: {
    zh: "下拉控件：切换后立即生效（即时类）",
    en: "Select control: applies immediately (instant)",
  },
  rowTelemetry: { zh: "匿名使用统计", en: "Anonymous usage stats" },
  rowTelemetryDesc: {
    zh: "复选控件：勾选即生效（即时类）",
    en: "Checkbox control: applies when toggled (instant)",
  },
  rowCanvasFloor: { zh: "画布最小字号", en: "Canvas min font size" },
  rowCanvasFloorDesc: {
    zh: "数字步进器（step 1，硬钳制）：检验控件高度与字号放大的协调性",
    en: "Number stepper (step 1, hard clamp): checks control height vs type scale harmony",
  },
  rowScaleHint: { zh: "字号基准", en: "Type base" },
  rowScaleHintDesc: {
    zh: "本行的 label=sm 档、说明=xs 档，随基准缩放",
    en: "Label uses sm rung, description xs — both scale with base",
  },

  chatUser: {
    zh: "工作流画布上的节点文字有点小，能把界面整体字号调大一点吗？",
    en: "Canvas node labels feel small — can we scale the whole UI type up a bit?",
  },
  chatAssistant1: {
    zh: "可以。这个预览把主字阶收敛到一个基准变量：",
    en: "Yes. This preview collapses the main ladder into one base variable:",
  },
  chatAssistantBullets: {
    zh: ["控件带（xs/sm/md）随基准 ±1–2px 同步移动；", "标题带（title/xl）保持对比层级。"],
    en: ["Control band (xs/sm/md) moves ±1–2px with the base;", "Title band (title/xl) keeps its contrast hierarchy."],
  },
  chatMeta: { zh: "助手 · 刚刚", en: "Assistant · just now" },
  chatCodeInline: "--vui-font-base",

  breadcrumbRoot: { zh: "工作台", en: "Workbench" },
  breadcrumbMid: { zh: "设置", en: "Settings" },
  breadcrumbLeaf: { zh: "字阶", en: "Type scale" },
  denseInputPlaceholder: { zh: "搜索或输入命令…", en: "Search or type a command…" },
  chipStable: { zh: "稳定", en: "Stable" },
  chipBeta: { zh: "Beta", en: "Beta" },
  chipDone: { zh: "已完成", en: "Done" },
  chipPending: { zh: "待处理", en: "Pending" },
  chipFailed: { zh: "失败", en: "Failed" },
  btnPrimary: { zh: "保存", en: "Save" },
  btnSecondary: { zh: "重置", en: "Reset" },
  btnGhost: { zh: "了解更多", en: "Learn more" },
  btnDanger: { zh: "删除", en: "Delete" },

  canvasKicker: { zh: "阶段 REGION", en: "STAGE REGION" },
  canvasTitle: { zh: "数据接入节点", en: "Ingest node" },
  canvasSubtitle: { zh: "运行中 · 每 5 分钟拉取", en: "Running · polls every 5 min" },
  canvasBadge: { zh: "自动重试", en: "auto-retry" },
  canvasMeta: { zh: "上次成功 12:03", en: "last ok 12:03" },
  canvasEmphasis: { zh: "重点标签", en: "Key label" },
  petStatus: { zh: "任务进行中", en: "Task running" },
  petSub: { zh: "已完成 3/7", en: "3/7 done" },
  petHeader: { zh: "桌宠", en: "Pet" },
  terminalLine: "$ vibe run --task font-scale",
  terminalOutput: "[ok] ladder derived in 4 bases",

  footerDerived: {
    zh: "本页的派生式字号为预览本地副本（fontScaleTokens.css）：仅把主字阶改写为 calc(基准±Npx)，颜色/圆角/行高等其余令牌照抄生产 tokens.css。",
    en: "The derived type tokens here are a preview-local copy (fontScaleTokens.css): only the main ladder is rewritten as calc(base±Npx); all other tokens mirror production tokens.css.",
  },
  footerFixed: {
    zh: "画布（--vui-font-canvas-*，9–15px）、桌宠（--vui-pet-*，固定 px）、xterm 终端（13px）是声明式固定密度轴，不参与派生。",
    en: "Canvas (--vui-font-canvas-*, 9–15px), pet (--vui-pet-*, fixed px) and the xterm terminal (13px) are declared fixed-density axes and do not participate in derivation.",
  },
  footerClamp: {
    zh: "生产集成时基准钳制 14–18px：控件高度（30px）固定，超出会挤压布局。",
    en: "Production integration clamps the base to 14–18px: control heights (30px) are fixed, larger bases would squeeze them.",
  },
  footerZeroDrift: {
    zh: "base=16 时逐档与生产现值零漂移（微字 9–13 / 2xs 12 / xs 14 / sm 15 / md 16 / chat 17 / lg 18 / title 19 / xl 22）。",
    en: "At base=16 every rung equals the production value (micro 9–13 / 2xs 12 / xs 14 / sm 15 / md 16 / chat 17 / lg 18 / title 19 / xl 22).",
  },
} as const;

export type CopyKey = keyof typeof COPY;
