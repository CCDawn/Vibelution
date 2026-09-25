import type { ConfigEditorMeta, ConfigEditorSection } from "../api/types";

import type { ConfigSettingsGroup, ConfigSettingsGroupId } from "./ConfigSettingsNavigation";
import { configSectionFieldCopy } from "./configSectionPresentation";

export type ConfigSettingsSearchHit = {
  groupId: ConfigSettingsGroupId;
  pageId: string;
  sectionId?: string;
  /** 叶子字段的绝对配置路径（如 ui.workbench_theme）；非字段条目缺省。 */
  fieldId?: string;
  title: string;
  detail: string;
  /** 非敏感短值的当前值摘要；secret/长值/复杂值不带（secret 永不进索引）。 */
  valueSummary?: string;
};

export type ConfigSettingsSearchDocument = ConfigSettingsSearchHit & {
  haystack: string;
  /** 名称子集（字段 label/组/页/分区名）：字段名命中的层级判定用。 */
  titleHaystack: string;
  /** 值摘要子集：值命中的层级判定用（secret 恒为空）。 */
  valueHaystack: string;
};

/** 值摘要的最大字符数（长值截断；secret 类字段永不生成摘要）。 */
const VALUE_SUMMARY_MAX_CHARS = 32;

export function buildConfigSettingsNavigationSearch(
  current: URLSearchParams | string,
  groupId: ConfigSettingsGroupId,
  pageId: string,
  focusSectionId?: string,
  focusFieldId?: string,
): string {
  const params = new URLSearchParams(current);
  params.set("section", groupId);
  params.set("page", pageId);
  if (focusSectionId) params.set("focus", focusSectionId);
  else params.delete("focus");
  if (focusSectionId && focusFieldId) params.set("field", focusFieldId);
  else params.delete("field");
  return `?${params.toString()}`;
}

export function resolveConfigSettingsFocus(
  previousKey: string,
  activeGroupId: string,
  activePageId: string,
  focusSectionId: string,
): { nextKey: string; shouldFocus: boolean } {
  if (!focusSectionId) return { nextKey: "", shouldFocus: false };
  const nextKey = `${activeGroupId}:${activePageId}:${focusSectionId}`;
  return { nextKey, shouldFocus: nextKey !== previousKey };
}

function normalizeSearchText(value: string): string {
  return value.trim().toLowerCase();
}

function pageForSection(
  groups: ConfigSettingsGroup[],
  sectionId: string,
): { groupId: ConfigSettingsGroupId; pageId: string; groupTitle: string; pageTitle: string } | null {
  for (const group of groups) {
    for (const page of group.pages) {
      if (page.memberSectionIds.includes(sectionId)) {
        return { groupId: group.id, pageId: page.id, groupTitle: group.title, pageTitle: page.title };
      }
    }
  }
  return null;
}

function sectionForMetaPath(
  editorSections: ConfigEditorSection[],
  path: string,
): ConfigEditorSection | null {
  const matches = editorSections.filter((section) => path === section.path || path.startsWith(`${section.path}.`));
  if (!matches.length) return null;
  return matches.sort((left, right) => right.path.length - left.path.length)[0] ?? null;
}

/** 不生成值摘要的字段种类（复杂/长文本/图像类；secret 单独红线排除）。 */
const KINDS_WITHOUT_VALUE_SUMMARY: ReadonlySet<string> = new Set([
  "secret",
  "multiline",
  "json",
  "string_list",
  "object",
  "object_list",
  "image",
]);

/**
 * 非敏感短值摘要：仅用于搜索索引与结果展示。
 * - secret 类字段返回空串（红线：secret 值绝不进索引/日志）；
 * - 布尔给开/关，select 优先给选项 label，数字/短文本直接给值；
 * - 多行与复杂结构（json/list/object/image/multiline）不给摘要；
 * - 超长文本截断到 32 字符。
 */
function safeValueSummary(
  meta: ConfigEditorMeta | undefined,
  value: unknown,
  language: "zh" | "en",
): string {
  if (value === undefined || value === null) {
    return "";
  }
  if (meta && KINDS_WITHOUT_VALUE_SUMMARY.has(meta.kind)) {
    return "";
  }
  if (typeof value === "boolean") {
    return value ? (language === "zh" ? "开" : "On") : language === "zh" ? "关" : "Off";
  }
  if (typeof value === "number") {
    return String(value);
  }
  if (typeof value !== "string") {
    return "";
  }
  let summary = value.replace(/\s*[\r\n]+\s*/g, " ").trim();
  if (!summary) {
    return "";
  }
  if (meta?.kind === "select") {
    const optionLabel = (meta.options ?? []).find((option) => option.value === value)?.label ?? "";
    if (optionLabel) {
      summary = optionLabel;
    }
  }
  if (summary.length > VALUE_SUMMARY_MAX_CHARS) {
    summary = `${summary.slice(0, VALUE_SUMMARY_MAX_CHARS)}…`;
  }
  return summary;
}

function readConfigValueAtPath(root: unknown, path: string): unknown {
  let current: unknown = root;
  for (const token of path.split(".").filter(Boolean)) {
    if (current === null || typeof current !== "object") {
      return undefined;
    }
    current = (current as Record<string, unknown>)[token];
  }
  return current;
}

export function buildConfigSettingsSearchIndex(options: {
  groups: ConfigSettingsGroup[];
  editorSections?: ConfigEditorSection[];
  editorMeta?: Record<string, ConfigEditorMeta>;
  /** 当前配置树（draft/committed），用于生成非敏感值摘要；缺省时无值摘要。 */
  configValues?: unknown;
  language?: "zh" | "en";
}): ConfigSettingsSearchDocument[] {
  const { groups, editorSections = [], editorMeta = {}, configValues, language = "zh" } = options;
  const documents: ConfigSettingsSearchDocument[] = [];

  for (const group of groups) {
    documents.push({
      groupId: group.id,
      pageId: group.pages[0]?.id ?? group.id,
      title: group.title,
      detail: group.summary,
      haystack: [group.id, group.title, group.summary].join(" "),
      titleHaystack: group.title,
      valueHaystack: "",
    });
    for (const page of group.pages) {
      documents.push({
        groupId: group.id,
        pageId: page.id,
        title: page.title,
        detail: group.title,
        haystack: [page.id, page.title, page.summary, group.title, ...page.memberSectionIds].join(" "),
        titleHaystack: page.title,
        valueHaystack: "",
      });
    }
  }

  for (const section of editorSections) {
    const located = pageForSection(groups, section.id);
    if (!located) continue;
    documents.push({
      groupId: located.groupId,
      pageId: located.pageId,
      sectionId: section.id,
      title: section.title,
      detail: [located.groupTitle, located.pageTitle, section.title].filter(Boolean).join(" · "),
      haystack: [section.id, section.path, section.title, section.summary, located.pageTitle, located.groupTitle].join(" "),
      titleHaystack: section.title,
      valueHaystack: "",
    });
  }

  for (const [path, meta] of Object.entries(editorMeta)) {
    const section = sectionForMetaPath(editorSections, path);
    const located = section ? pageForSection(groups, section.id) : null;
    if (!located) continue;
    const label = String(meta.label || path);
    const hint = String(meta.hint || "");
    const isLeafField = meta.kind !== "object" && meta.kind !== "object_list";
    // 字段级条目：label 取前端双语字段文案（zh/en 都进 haystack，跨语言可搜）。
    const zhCopy = configSectionFieldCopy(path, "zh");
    const enCopy = configSectionFieldCopy(path, "en");
    const displayLabel = (language === "zh" ? zhCopy?.label : enCopy?.label) ?? label;
    const labels = Array.from(new Set([displayLabel, label, zhCopy?.label ?? "", enCopy?.label ?? ""].filter(Boolean)));
    const hints = [zhCopy?.hint ?? "", enCopy?.hint ?? "", hint].filter(Boolean);
    const pathTail = path.split(".").filter(Boolean).at(-1) ?? path;
    const valueSummary = isLeafField ? safeValueSummary(meta, readConfigValueAtPath(configValues, path), language) : undefined;
    const sectionTitle = section?.title ?? "";
    documents.push({
      groupId: located.groupId,
      pageId: located.pageId,
      sectionId: section?.id,
      fieldId: isLeafField ? path : undefined,
      title: displayLabel,
      detail: [located.groupTitle, located.pageTitle, sectionTitle].filter(Boolean).join(" · "),
      valueSummary,
      haystack: [path, pathTail, ...labels, ...hints, sectionTitle, located.pageTitle, located.groupTitle, valueSummary ?? ""].join(" "),
      titleHaystack: [...labels, pathTail].join(" "),
      valueHaystack: valueSummary ?? "",
    });
  }

  return documents;
}

/** 命中层级：字段名命中 > 值命中 > 说明/路径等其余命中。 */
type SearchHitTier = 1 | 2 | 3;

function hitTier(document: ConfigSettingsSearchDocument, tokens: readonly string[]): SearchHitTier {
  const title = normalizeSearchText(document.titleHaystack);
  if (title && tokens.every((token) => title.includes(token))) {
    return 3;
  }
  const value = normalizeSearchText(document.valueHaystack);
  if (value && tokens.every((token) => value.includes(token))) {
    return 2;
  }
  return 1;
}

export function searchConfigSettings(
  documents: ConfigSettingsSearchDocument[],
  query: string,
  limit = 12,
): ConfigSettingsSearchHit[] {
  const normalized = normalizeSearchText(query);
  if (!normalized) return [];
  const tokens = normalized.split(/\s+/).filter(Boolean);
  const seen = new Set<string>();
  const hits: Array<ConfigSettingsSearchHit & { tier: SearchHitTier }> = [];
  for (const document of documents) {
    const haystack = normalizeSearchText(document.haystack);
    if (!tokens.every((token) => haystack.includes(token))) continue;
    const key = `${document.groupId}:${document.pageId}:${document.sectionId ?? ""}:${document.fieldId ?? ""}:${document.title}`;
    if (seen.has(key)) continue;
    seen.add(key);
    hits.push({
      groupId: document.groupId,
      pageId: document.pageId,
      sectionId: document.sectionId,
      fieldId: document.fieldId,
      title: document.title,
      detail: document.detail,
      valueSummary: document.valueSummary,
      tier: hitTier(document, tokens),
    });
  }
  // 层级降序（字段名命中 > 值命中 > 说明命中），同层级保持索引原序（稳定排序）。
  return hits
    .map((hit, order) => ({ hit, order }))
    .sort((left, right) => right.hit.tier - left.hit.tier || left.order - right.order)
    .map(({ hit }) => {
      const { tier: _tier, ...rest } = hit;
      return rest;
    })
    .slice(0, limit);
}
