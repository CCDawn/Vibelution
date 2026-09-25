/**
 * 预览演示数据 —— 字段名/默认值照真实配置编写：
 * - 分区与字段来源 core/web/services/config_editor_schema.py EDITOR_SECTION_SPECS
 *   （"context-compression" → context_compression）；
 * - 默认值/约束来源 config/models.py ContextCompressionConfig（enabled=true、
 *   max_token_limit=16000、summary_max_chars=200、summary_chars 四级字数、
 *   micro_compact_tool_whitelist 内置白名单）；
 * - 控件混合按预览要求：布尔×2、下拉×1、数字×2（带单位）、字符串列表×1、json×1。
 * 不连后端；compression_model 的下拉选项为演示用常见轻量模型（生产中该字段是自由文本）。
 */

import type { FieldDeclaration, SelectOption } from "./settingsModel";

const MICRO_COMPACT_DEFAULT_TOOL_WHITELIST: readonly string[] = [
  "read_file_tool",
  "grep_search_tool",
  "glob_tool",
  "code_symbol_tool",
  "project_search_tool",
  "web_search_tool",
  "web_fetch_tool",
  "batch_web_search_tool",
  "paper_search_tool",
  "news_search_tool",
  "search_summarize_sources_tool",
  "history_search_tool",
  "history_fetch_tool",
  "history_timeline_tool",
  "cli_tool",
  "exec_command",
];

const COMPRESSION_MODEL_OPTIONS: readonly SelectOption[] = [
  { value: "qwen-turbo", label: "qwen-turbo", labelEn: "qwen-turbo" },
  { value: "qwen-flash", label: "qwen-flash", labelEn: "qwen-flash" },
  { value: "glm-4-flash", label: "glm-4-flash", labelEn: "glm-4-flash" },
  { value: "deepseek-chat", label: "deepseek-chat", labelEn: "deepseek-chat" },
];

export const SECTION_TITLE = "上下文与分析";
export const SECTION_TITLE_EN = "Context & Analysis";
export const SECTION_SUBTITLE = "上下文压缩";
export const SECTION_SUBTITLE_EN = "Context Compression";

/** 七个演示字段：字段声明即 A 行原语与 C 保存模型的数据源。 */
export const PREVIEW_FIELDS: readonly FieldDeclaration[] = [
  {
    path: "context_compression.enabled",
    label: "启用上下文压缩",
    labelEn: "Enable context compression",
    description: "是否启用上下文压缩。超过触发阈值时把旧对话压缩为摘要。",
    descriptionEn: "Compress older conversation into summaries once the token threshold is hit.",
    kind: "boolean",
    saveMode: "immediate",
    defaultValue: true,
  },
  {
    path: "context_compression.micro_compact_enabled",
    label: "微压缩层",
    labelEn: "Micro-compact tier",
    description:
      "token 进入微压缩区间时先替换白名单只读工具的旧工具结果，重估低于全量触发线则不触发全量压缩。",
    descriptionEn:
      "Replace old whitelisted read-only tool results first; skip full compression when re-estimated tokens fall back under the line.",
    kind: "boolean",
    saveMode: "immediate",
    defaultValue: true,
  },
  {
    path: "context_compression.compression_model",
    label: "压缩用模型",
    labelEn: "Compression model",
    description: "执行摘要压缩的轻量模型。",
    descriptionEn: "Lightweight model used to produce summaries.",
    kind: "select",
    saveMode: "immediate",
    defaultValue: "qwen-turbo",
    options: COMPRESSION_MODEL_OPTIONS,
  },
  {
    path: "context_compression.max_token_limit",
    label: "压缩触发阈值",
    labelEn: "Compression trigger threshold",
    description: "上下文 token 超过该值触发全量压缩。",
    descriptionEn: "Full compression starts once context tokens exceed this value.",
    kind: "number",
    saveMode: "draft",
    defaultValue: 16000,
    unit: "tokens",
    unitEn: "tokens",
    min: 1000,
    max: 200000,
    step: 1000,
  },
  {
    path: "context_compression.summary_max_chars",
    label: "摘要最大字符数",
    labelEn: "Summary max chars",
    description: "压缩摘要的最大字符数（模型约束上限 1000）。",
    descriptionEn: "Maximum characters for a compression summary (model cap: 1000).",
    kind: "number",
    saveMode: "draft",
    defaultValue: 200,
    unit: "字符",
    unitEn: "chars",
    min: 50,
    max: 1000,
    step: 50,
  },
  {
    path: "context_compression.micro_compact_tool_whitelist",
    label: "微压缩白名单",
    labelEn: "Micro-compact tool whitelist",
    description:
      "可被微压缩替换的大输出只读/检索类工具；每行一项，留空列表表示使用内置默认白名单。",
    descriptionEn:
      "Read-only/retrieval tools eligible for micro-compact; one per line. An empty list means the built-in default whitelist.",
    kind: "string_list",
    saveMode: "draft",
    defaultValue: MICRO_COMPACT_DEFAULT_TOOL_WHITELIST,
  },
  {
    path: "context_compression.summary_chars",
    label: "各级摘要字数",
    labelEn: "Per-level summary chars",
    description: "light/standard/deep/emergency 四级压缩各自的摘要字数上限。",
    descriptionEn: "Summary char caps for the light/standard/deep/emergency compression levels.",
    kind: "json",
    saveMode: "draft",
    defaultValue: { light: 500, standard: 1000, deep: 2000, emergency: 3000 },
  },
];

/** json 校验演示用的非法样例（末尾多余逗号，错误定位在最末属性后）。 */
export const JSON_ERROR_SAMPLE =
  '{\n  "light": 500,\n  "standard": 1000,\n  "deep": 2000,\n  "emergency": 3000,\n}';

/** list 校验演示用的非法样例（大写与非法字符两行）。 */
export const LIST_INVALID_SAMPLE = [
  "read_file_tool",
  "Grep_Search_Tool",
  "web_search_tool",
  "bad tool name!",
  "exec_command",
].join("\n");

export type PreviewBootState =
  | "view-cards"
  | "view-rows"
  | "edit-clean"
  | "edit-dirty"
  | "json-error"
  | "list-invalid"
  | "saved";

export const PREVIEW_BOOT_STATES: readonly PreviewBootState[] = [
  "view-cards",
  "view-rows",
  "edit-clean",
  "edit-dirty",
  "json-error",
  "list-invalid",
  "saved",
];

/** URL ?state= 确定性初始态（截图与人工复现用；每个 state 首屏即现目标态）。 */
export function readPreviewBootState(): PreviewBootState {
  const raw = new URLSearchParams(window.location.search).get("state");
  return PREVIEW_BOOT_STATES.includes(raw as PreviewBootState)
    ? (raw as PreviewBootState)
    : "view-rows";
}

export type Lang = "zh" | "en";

/** 底部说明区条目（数组，独立于单语文案表）。 */
export const NOTES: Record<Lang, readonly string[]> = {
  zh: [
    "本页是对齐 ZCode 设置面波次 1 的隔离预览：行原语、控件升级与保存模型均为前端模拟，不改任何生产代码。",
    "「保存」是模拟动作：真实集成时走 previewConfigDraft → apply 管线，并按字段声明（布尔/下拉即时，其余草稿）接入即时/草稿双轨。",
    "徽标语义：已生效=即时类字段已变更并直接提交；待保存=草稿类字段已修改、等待显式保存；保存/放弃后徽标清除。",
    "list 字段以微压缩工具白名单为真实样例：逐行校验注册名格式；URL 列表等其它逐行校验同型。",
  ],
  en: [
    "Isolated wave-1 preview for aligning the settings surface with ZCode: row primitive, control upgrades and the save model are simulated; no production code changes.",
    "'Save' is simulated: real integration goes through the previewConfigDraft → apply pipeline with per-field declarations (booleans/selects immediate; the rest draft-based).",
    "Badge semantics: Applied = an immediate field changed and committed directly; Pending = a draft field modified, awaiting explicit save; badges clear after save/discard.",
    "The list field uses the real micro-compact whitelist: per-line tool-name validation; other per-line formats (e.g. URL lists) follow the same shape.",
  ],
};

/** 双语 UI 文案（照 ConfigShortcutsPanel 预览的双语做法）。 */
export const COPY = {
  badgePreview: { zh: "隔离预览 · 不进生产路由", en: "Isolated preview · not in production build" },
  badgeBranch: { zh: "codex/zcode-settings-align-w1", en: "codex/zcode-settings-align-w1" },
  densityRows: { zh: "行列表（新密度）", en: "Rows (new density)" },
  densityCards: { zh: "卡片流（现状）", en: "Cards (current)" },
  densityLabel: { zh: "密度对比", en: "Density" },
  modeView: { zh: "查看态", en: "View" },
  modeEdit: { zh: "编辑态", en: "Edit" },
  modeLabel: { zh: "模式", en: "Mode" },
  statusApplied: { zh: "已生效", en: "Applied" },
  statusPending: { zh: "待保存", en: "Pending" },
  saveBarTitle: { zh: "外部配置草稿", en: "External config draft" },
  saveBarPending: { zh: "待保存", en: "pending" },
  saveBarCountSuffix: { zh: "项", en: "item(s)" },
  saveAll: { zh: "保存", en: "Save" },
  discardAll: { zh: "放弃更改", en: "Discard" },
  leaveSimulate: { zh: "离开页面（模拟）", en: "Leave page (simulate)" },
  toastSaved: { zh: "已保存到外部配置", en: "Saved to the external config" },
  toastDiscarded: { zh: "已放弃草稿更改", en: "Draft changes discarded" },
  toastSavedLeave: { zh: "已保存并离开（模拟）", en: "Saved and left (simulated)" },
  toastDiscardLeave: { zh: "已放弃更改并离开（模拟）", en: "Changes discarded, left (simulated)" },
  dialogLeaveTitle: { zh: "有未保存的更改", en: "Unsaved changes" },
  dialogLeaveDescription: {
    zh: "还有草稿字段未保存到外部配置。离开前要保存吗？",
    en: "Some draft fields are not saved to the external config yet. Save before leaving?",
  },
  dialogSaveLeave: { zh: "保存并离开", en: "Save & leave" },
  dialogDiscardLeave: { zh: "放弃并离开", en: "Discard & leave" },
  dialogStay: { zh: "留下", en: "Stay" },
  jsonValid: { zh: "✓ 格式正确", en: "✓ Valid JSON" },
  jsonInvalidPrefix: { zh: "JSON 解析失败：", en: "JSON parse failed: " },
  jsonErrorAt: { zh: "（第", en: " (line " },
  jsonErrorLine: { zh: "行，第", en: ", column " },
  jsonErrorCol: { zh: "列）", en: ")" },
  listLineCount: { zh: "行", en: "line(s)" },
  listValidCount: { zh: "项有效", en: "valid item(s)" },
  listErrorCount: { zh: "项非法", en: "invalid item(s)" },
  listLinePrefix: { zh: "第", en: "Line " },
  listLineMid: { zh: "行：", en: ": " },
  numberRangeHint: { zh: "范围", en: "range" },
  numberStepHint: { zh: "步进", en: "step" },
  readMoreItems: { zh: "等", en: "items total: " },
  itemsTotal: { zh: "项", en: " items" },
  jsonValueSummary: { zh: "4 个层级", en: "4 levels" },
  booleanOn: { zh: "开启", en: "On" },
  booleanOff: { zh: "关闭", en: "Off" },
  saveBlockedReason: {
    zh: "有非法草稿（见红字错误），修正后才能保存",
    en: "Invalid draft present (see inline errors); fix it before saving",
  },
  notesTitle: { zh: "关于本预览", en: "About this preview" },
  footnoteState: { zh: "确定态深链", en: "Deterministic states" },
};

export type CopyKey = keyof typeof COPY;

export function copyText(key: CopyKey, lang: Lang): string {
  return COPY[key][lang];
}
