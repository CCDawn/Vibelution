/**
 * Pure field-editor + draft-save model for the structured config editor
 * (settings-align wave 1). React-free; bilingual copy stays in CONFIG_COPY —
 * validators return issue codes/params, the route maps them to copy.
 *
 * Three responsibilities:
 * - Control validation: json (live parse with first-error line/column),
 *   number (schema min/max hard bounds), string_list (per-line validation —
 *   tool-name lists get name-pattern + duplicate errors, generic lists get
 *   blank-line/whitespace warnings only). Invalid drafts no longer silently
 *   store the raw string: they block save with inline errors instead.
 * - Raw-text draft leaves: json/number/string_list editors buffer their text
 *   in the section draft; parsing happens through parseDraftLeafValue so the
 *   pending diff, the save payload and the global pending count all share one
 *   normalization.
 * - Save-mode semantics: boolean/select fields are immediate (see
 *   shouldImmediateApplyFieldKind in configApplyModel) and never count as
 *   pending drafts.
 */
import type { ConfigEditorMeta } from "../../api/types";
import { isUiLanguageFieldPath, shouldImmediateApplyFieldKind } from "./configApplyModel";

/** Kinds whose editor buffers raw text in the draft instead of a runtime value. */
export const RAW_TEXT_EDITOR_KINDS = new Set(["json", "number", "string_list"]);

export type JsonParseIssue = {
  code: "jsonInvalid";
  message: string;
  /** 1-based position of the first parse error; null when the engine gives none. */
  line: number | null;
  column: number | null;
};

export type JsonValidation = { ok: true; value: unknown } | { ok: false; issue: JsonParseIssue };

/**
 * json 字段校验：JSON.parse 失败时定位首个解析错误位置。
 * 从错误消息里抽取 "position N"（V8/JSC 均带），再按原文换行折算行列。
 */
export function validateJsonText(raw: string): JsonValidation {
  try {
    return { ok: true, value: JSON.parse(raw) };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const match = message.match(/position (\d+)/i);
    if (match) {
      const position = Number(match[1]);
      const before = raw.slice(0, position);
      const lines = before.split(/\r?\n/);
      const line = lines.length;
      const column = (lines[lines.length - 1]?.length ?? 0) + 1;
      return { ok: false, issue: { code: "jsonInvalid", message, line, column } };
    }
    return { ok: false, issue: { code: "jsonInvalid", message, line: null, column: null } };
  }
}

/** json 的稳定展示串（2 空格缩进），查看态/进入编辑时使用。 */
export function formatJsonValue(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export type NumberBounds = {
  min?: { value: number; exclusive: boolean };
  max?: { value: number; exclusive: boolean };
};

/** Schema bounds for a number field; absent keys mean "no invented range". */
export function numberBounds(meta: ConfigEditorMeta | undefined): NumberBounds {
  const min =
    typeof meta?.minimum === "number"
      ? { value: meta.minimum, exclusive: false }
      : typeof meta?.exclusiveMinimum === "number"
        ? { value: meta.exclusiveMinimum, exclusive: true }
        : undefined;
  const max =
    typeof meta?.maximum === "number"
      ? { value: meta.maximum, exclusive: false }
      : typeof meta?.exclusiveMaximum === "number"
        ? { value: meta.exclusiveMaximum, exclusive: true }
        : undefined;
  return { min, max };
}

export type NumberIssue =
  | { code: "numberRequired" }
  | { code: "numberInvalid"; value: string }
  | { code: "numberBelowMin"; bound: number; exclusive: boolean }
  | { code: "numberAboveMax"; bound: number; exclusive: boolean };

export type NumberValidation = { ok: true; value: number } | { ok: false; issue: NumberIssue };

/**
 * number 字段校验：空值/非数字拒绝；schema min/max 硬边界拒绝。
 * 没有真实 schema 边界时不制造范围。
 */
export function validateNumberText(raw: string, bounds: NumberBounds): NumberValidation {
  const trimmed = raw.trim();
  if (trimmed === "") {
    return { ok: false, issue: { code: "numberRequired" } };
  }
  const value = Number(trimmed);
  if (!Number.isFinite(value)) {
    return { ok: false, issue: { code: "numberInvalid", value: trimmed } };
  }
  if (bounds.min) {
    const below = bounds.min.exclusive ? value <= bounds.min.value : value < bounds.min.value;
    if (below) {
      return { ok: false, issue: { code: "numberBelowMin", bound: bounds.min.value, exclusive: bounds.min.exclusive } };
    }
  }
  if (bounds.max) {
    const above = bounds.max.exclusive ? value >= bounds.max.value : value > bounds.max.value;
    if (above) {
      return { ok: false, issue: { code: "numberAboveMax", bound: bounds.max.value, exclusive: bounds.max.exclusive } };
    }
  }
  return { ok: true, value };
}

/**
 * Stepper granularity derived from the field's own shape (never invented data):
 * integer-valued fields/bounds step by 1, float-shaped fields by 0.1.
 */
export function deriveNumberStep(meta: ConfigEditorMeta | undefined, committedValue: unknown): number {
  const candidates = [committedValue, meta?.minimum, meta?.exclusiveMinimum, meta?.maximum, meta?.exclusiveMaximum]
    .filter((candidate): candidate is number => typeof candidate === "number");
  const allIntegers = candidates.every((candidate) => Number.isInteger(candidate));
  return allIntegers ? 1 : 0.1;
}

/** 步进器下一步取值：±step 后夹到 schema 边界内（保留整数/浮点语义）。 */
export function stepNumberValue(
  current: number,
  bounds: NumberBounds,
  direction: 1 | -1,
  step: number,
): number {
  const next = current + direction * step;
  const lower = bounds.min ? (bounds.min.exclusive ? bounds.min.value + step : bounds.min.value) : -Number.MAX_SAFE_INTEGER;
  const upper = bounds.max ? (bounds.max.exclusive ? bounds.max.value - step : bounds.max.value) : Number.MAX_SAFE_INTEGER;
  const clamped = Math.min(Math.max(next, lower), upper);
  return Math.round(clamped * 1e6) / 1e6;
}

/** Paths whose string lists hold tool registration names (per-line name format + dedupe). */
export function isToolNameListPath(path: string): boolean {
  const lastSegment = String(path || "").split(".").pop() ?? "";
  return /tool/i.test(lastSegment) && /(whitelist|allowlist)s?$/i.test(lastSegment);
}

export type ListIssueCode =
  | { code: "listInvalidToolName"; value: string }
  | { code: "listDuplicateItem"; value: string }
  | { code: "listBlankLine" }
  | { code: "listWhitespace"; value: string };

export type ListIssue = { line: number; severity: "error" | "warning" } & ListIssueCode;

export type ListLineReport = {
  /** 1 起的行号（与 textarea 视觉行一致，空行跳过但行号保留）。 */
  line: number;
  value: string;
  ok: boolean;
};

export type ListValidation = {
  ok: boolean;
  values: string[];
  lines: ListLineReport[];
  issues: ListIssue[];
  errorCount: number;
};

const TOOL_NAME_PATTERN = /^[a-z][a-z0-9_]*$/;

/**
 * string_list 字段校验：textarea 按行拆分，空行跳过。
 * 工具名单类路径（*tool_whitelist）做注册名格式校验 + 重复项判非法；
 * 通用列表只对空行/首尾空格给自动清理提示（warning，不阻塞保存）。
 */
export function validateListText(raw: string, options: { toolNames?: boolean } = {}): ListValidation {
  const toolNames = options.toolNames ?? false;
  const lines = raw.split(/\r?\n/);
  const issues: ListIssue[] = [];
  const reports: ListLineReport[] = [];
  const values: string[] = [];
  for (let index = 0; index < lines.length; index += 1) {
    const text = lines[index] ?? "";
    const trimmed = text.trim();
    const lineNumber = index + 1;
    if (trimmed === "") {
      issues.push({ line: lineNumber, severity: "warning", code: "listBlankLine" });
      continue;
    }
    if (trimmed !== text) {
      issues.push({ line: lineNumber, severity: "warning", code: "listWhitespace", value: text });
    }
    if (toolNames && !TOOL_NAME_PATTERN.test(trimmed)) {
      issues.push({ line: lineNumber, severity: "error", code: "listInvalidToolName", value: trimmed });
      reports.push({ line: lineNumber, value: trimmed, ok: false });
      continue;
    }
    reports.push({ line: lineNumber, value: trimmed, ok: true });
    values.push(trimmed);
  }
  const seen = new Set<string>();
  let errorCount = issues.filter((issue) => issue.severity === "error").length;
  for (const report of reports) {
    if (!report.ok) {
      continue;
    }
    if (toolNames && seen.has(report.value)) {
      report.ok = false;
      issues.push({ line: report.line, severity: "error", code: "listDuplicateItem", value: report.value });
      errorCount += 1;
    } else {
      seen.add(report.value);
    }
  }
  return { ok: errorCount === 0, values, lines: reports, issues, errorCount };
}

/** list 的 textarea 展示串（一行一项），查看态/进入编辑时使用。 */
export function formatListValue(values: readonly unknown[]): string {
  return values.map((value) => String(value)).join("\n");
}

/** 编辑器的受控展示文本：草稿里的原始串优先，否则格式化 committed 值。 */
export function fieldEditorDisplayText(
  kind: ConfigEditorMeta["kind"] | "background_image" | undefined,
  draftLeaf: unknown,
  committedLeaf: unknown,
): string {
  const resolvedKind = kind === "background_image" ? "text" : kind ?? "text";
  if (RAW_TEXT_EDITOR_KINDS.has(resolvedKind)) {
    if (typeof draftLeaf === "string") {
      return draftLeaf;
    }
    if (resolvedKind === "json") {
      return formatJsonValue(committedLeaf);
    }
    if (resolvedKind === "string_list") {
      return formatListValue(Array.isArray(committedLeaf) ? committedLeaf : []);
    }
    return committedLeaf == null ? "" : String(committedLeaf);
  }
  return committedLeaf == null ? "" : String(committedLeaf);
}

export type DraftLeafResolution = { ok: true; value: unknown } | { ok: false; issue: ListIssue | NumberIssue | JsonParseIssue };

/** 把一个草稿叶子解析回运行时值（原始文本 kinds 才有解析失败的可能）。 */
export function parseDraftLeafValue(
  meta: ConfigEditorMeta | undefined,
  draftLeaf: unknown,
): DraftLeafResolution {
  if (typeof draftLeaf !== "string") {
    return { ok: true, value: draftLeaf };
  }
  if (meta?.kind === "json") {
    const result = validateJsonText(draftLeaf);
    return result.ok ? result : { ok: false, issue: result.issue };
  }
  if (meta?.kind === "number") {
    const result = validateNumberText(draftLeaf, numberBounds(meta));
    return result.ok ? result : { ok: false, issue: result.issue };
  }
  if (meta?.kind === "string_list") {
    const result = validateListText(draftLeaf, { toolNames: isToolNameListPath(meta.path) });
    const firstError = result.issues.find((issue) => issue.severity === "error");
    if (firstError) {
      return { ok: false, issue: firstError };
    }
    return { ok: true, value: result.values };
  }
  return { ok: true, value: draftLeaf };
}

export function configValuesEqual(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export type DraftLeafMetaResolver = (path: string) => ConfigEditorMeta | undefined;

export type PendingDraftLeaf = {
  path: string;
  valid: boolean;
};

/**
 * 待保存叶子收集（全局保存条计数与非法阻塞的口径）：
 * - 只统计草稿类字段（boolean/select 是即时类，永远不会滞留草稿）；
 * - ui.language 是专用端点字段（单一写入方，不走草稿），同样永不滞留：
 *   语言切换后工作区回读会把 committed 换成新语言值，若按普通字段比较，
 *   未重开的分区草稿会把旧语言误报成「待保存」并折进下一次 apply；
 * - 原始文本 kinds 先按 schema 解析再与 committed 比较，"16000" 与 16000
 *   不会误报为已修改；解析失败的叶子计入 pending 且 valid=false。
 */
export function collectPendingDraftLeaves(options: {
  draft: unknown;
  committed: unknown;
  path: string;
  metaAt: DraftLeafMetaResolver;
}): PendingDraftLeaf[] {
  const { draft, committed, path, metaAt } = options;
  const meta = metaAt(path);
  if (meta && (shouldImmediateApplyFieldKind(meta.kind, path) || isUiLanguageFieldPath(path))) {
    return [];
  }
  if (isPlainRecord(draft) && isPlainRecord(committed)) {
    const pending: PendingDraftLeaf[] = [];
    const keys = new Set([...Object.keys(draft), ...Object.keys(committed)]);
    for (const key of keys) {
      pending.push(
        ...collectPendingDraftLeaves({
          draft: draft[key],
          committed: committed[key],
          path: path ? `${path}.${key}` : key,
          metaAt,
        }),
      );
    }
    return pending;
  }
  if (Array.isArray(draft) && Array.isArray(committed)) {
    const pending: PendingDraftLeaf[] = [];
    if (meta?.kind === "object_list") {
      const length = Math.max(draft.length, committed.length);
      for (let index = 0; index < length; index += 1) {
        pending.push(
          ...collectPendingDraftLeaves({
            draft: draft[index],
            committed: committed[index],
            path: `${path}.${index}`,
            metaAt,
          }),
        );
      }
      return pending;
    }
    // 标量数组（string_list 等）作为单叶子整体比较。
  }
  const resolution = parseDraftLeafValue(meta, draft);
  if (!resolution.ok) {
    return [{ path, valid: false }];
  }
  if (configValuesEqual(resolution.value, committed)) {
    return [];
  }
  return [{ path, valid: true }];
}

export type DraftSaveResolution =
  | { ok: true; value: unknown }
  | { ok: false; invalid: Array<{ path: string; issue: ListIssue | NumberIssue | JsonParseIssue }> };

/**
 * 分区保存前的整树解析：把草稿里的原始文本叶子解析为运行时值；
 * 任一叶子非法即整体拒绝（非法阻塞分区保存），错误带绝对路径供行内定位。
 */
export function resolveDraftSubtreeForSave(options: {
  draft: unknown;
  path: string;
  metaAt: DraftLeafMetaResolver;
}): DraftSaveResolution {
  const { draft, path, metaAt } = options;
  const meta = metaAt(path);
  if (isPlainRecord(draft)) {
    const next: Record<string, unknown> = {};
    const invalid: Array<{ path: string; issue: ListIssue | NumberIssue | JsonParseIssue }> = [];
    for (const key of Object.keys(draft)) {
      const childPath = path ? `${path}.${key}` : key;
      const child = resolveDraftSubtreeForSave({ draft: draft[key], path: childPath, metaAt });
      if (child.ok) {
        next[key] = child.value;
      } else {
        invalid.push(...child.invalid);
      }
    }
    return invalid.length ? { ok: false, invalid } : { ok: true, value: next };
  }
  if (Array.isArray(draft) && meta?.kind === "object_list") {
    const next: unknown[] = [];
    const invalid: Array<{ path: string; issue: ListIssue | NumberIssue | JsonParseIssue }> = [];
    for (let index = 0; index < draft.length; index += 1) {
      const child = resolveDraftSubtreeForSave({ draft: draft[index], path: `${path}.${index}`, metaAt });
      if (child.ok) {
        next.push(child.value);
      } else {
        invalid.push(...child.invalid);
      }
    }
    return invalid.length ? { ok: false, invalid } : { ok: true, value: next };
  }
  const resolution = parseDraftLeafValue(meta, draft);
  return resolution.ok ? { ok: true, value: resolution.value } : { ok: false, invalid: [{ path, issue: resolution.issue }] };
}
