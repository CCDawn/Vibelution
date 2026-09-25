/**
 * 预览核心纯逻辑 —— 字段声明、校验、行状态机、保存模型（对齐 ZCode 设置面波次 1）。
 *
 * 三个对齐点在这里收敛为可测的纯函数：
 * - A 行原语：字段声明（label/description/控件形态）驱动行渲染；
 * - B 控件升级：json 实时校验（定位首个解析错误）、number min/max 硬校验、
 *   list 逐行校验（非法行标红+行号），不再静默存原始串；
 * - C 保存模型：布尔/下拉=即时类（committed 直接变更，徽标「已生效」）；
 *   文本/数字/列表/json=草稿类（draft 缓冲，徽标「待保存」，显式保存才提交）。
 *
 * 数据照 core/web/services/config_editor_schema.py 的 EDITOR_SECTION_SPECS 与
 * config/models.py 的 ContextCompressionConfig 真实字段/默认值编写；本模块不含 React。
 */

export type FieldKind = "boolean" | "select" | "number" | "string_list" | "json";

/** C 保存模型：字段级声明。布尔/下拉即时生效；文本/数字/列表/json 走草稿+显式保存。 */
export type SaveMode = "immediate" | "draft";

/** 行右侧状态徽标三态：clean=默认无 / applied=已生效（品牌色系）/ pending=待保存（中性强调）。 */
export type RowStatus = "clean" | "applied" | "pending";

export type SelectOption = {
  value: string;
  label: string;
  labelEn: string;
};

export type FieldDeclaration = {
  /** 相对 context_compression 的字段路径（真实配置路径的后两段）。 */
  path: string;
  label: string;
  labelEn: string;
  description: string;
  descriptionEn: string;
  kind: FieldKind;
  saveMode: SaveMode;
  defaultValue: unknown;
  /** number 单位后缀（展示用，不参与数值）。 */
  unit?: string;
  unitEn?: string;
  /** number 硬边界（照 config/models.py Field 的 ge/gt/le 约束）。 */
  min?: number;
  max?: number;
  /** number 步长（步进器 −/+）。 */
  step?: number;
  options?: readonly SelectOption[];
};

/** 校验结果：ok=false 时必须带可读错误，调用方直接行内呈现（不再静默吞掉）。 */
export type ValidationResult<T> = { ok: true; value: T } | { ok: false; error: string };

/** json 解析错误定位（行/列从 1 计；拿不到位置时定位为 null，错误文案仍给出）。 */
export type JsonParseFailure = {
  ok: false;
  error: string;
  line: number | null;
  column: number | null;
};
export type JsonParseSuccess = { ok: true; value: unknown };

const TOOL_NAME_PATTERN = /^[a-z][a-z0-9_]*$/;

/**
 * json 字段校验：JSON.parse 失败时定位首个解析错误位置。
 * 从错误消息里抽取 "position N"（V8/JSC 均带），再按原文换行折算行列。
 */
export function validateJsonText(raw: string): JsonParseSuccess | JsonParseFailure {
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
      return { ok: false, error: message, line, column };
    }
    return { ok: false, error: message, line: null, column: null };
  }
}

/** json 的稳定展示串（2 空格缩进），查看态/进入编辑时使用。 */
export function formatJsonValue(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

/**
 * number 字段校验：空值/非数字拒绝；min/max 硬边界拒绝。
 * 步进与手输共用这一条路径，保证「无范围」旧形态不再出现。
 */
export function validateNumberText(
  raw: string,
  field: FieldDeclaration,
): ValidationResult<number> {
  const trimmed = raw.trim();
  if (trimmed === "") {
    return { ok: false, error: "请输入数值" };
  }
  const value = Number(trimmed);
  if (!Number.isFinite(value)) {
    return { ok: false, error: `「${trimmed}」不是合法数字` };
  }
  if (field.min !== undefined && value < field.min) {
    return { ok: false, error: `不能小于最小值 ${field.min}` };
  }
  if (field.max !== undefined && value > field.max) {
    return { ok: false, error: `不能大于最大值 ${field.max}` };
  }
  return { ok: true, value };
}

/** 步进器下一步取值：±step 后夹到 [min, max]（保持整数语义）。 */
export function stepNumberValue(current: number, field: FieldDeclaration, direction: 1 | -1): number {
  const step = field.step ?? 1;
  const next = current + direction * step;
  const clamped = Math.min(
    Math.max(next, field.min ?? -Number.MAX_SAFE_INTEGER),
    field.max ?? Number.MAX_SAFE_INTEGER,
  );
  return Math.round(clamped * 1e6) / 1e6;
}

/** 单行校验结果（list 字段：非法行标红 + 行号错误提示的依据）。 */
export type ListLineReport = {
  /** 1 起的行号（与 textarea 视觉行一致，空行跳过但行号保留）。 */
  line: number;
  value: string;
  ok: boolean;
  error?: string;
};

export type ListValidation = {
  ok: boolean;
  values: string[];
  lines: ListLineReport[];
  errorCount: number;
};

/**
 * string_list 字段校验：textarea 按行拆分，空行跳过；其余行必须是合法工具注册名
 * （^[a-z][a-z0-9_]*$，与 config/models.py 的 MICRO_COMPACT_DEFAULT_TOOL_WHITELIST 同构）。
 * 预览以工具白名单为真实感样例（URL 列表的逐行校验同型）。
 */
export function validateListText(raw: string): ListValidation {
  const lines = raw.split(/\r?\n/);
  const reports: ListLineReport[] = [];
  const values: string[] = [];
  for (let index = 0; index < lines.length; index += 1) {
    const text = lines[index]?.trim() ?? "";
    if (text === "") {
      continue;
    }
    if (!TOOL_NAME_PATTERN.test(text)) {
      reports.push({
        line: index + 1,
        value: text,
        ok: false,
        error: "不是合法工具注册名（小写字母开头，仅小写字母/数字/下划线）",
      });
      continue;
    }
    reports.push({ line: index + 1, value: text, ok: true });
    values.push(text);
  }
  const seen = new Set<string>();
  let errorCount = reports.filter((report) => !report.ok).length;
  for (const report of reports) {
    if (!report.ok) {
      continue;
    }
    if (seen.has(report.value)) {
      report.ok = false;
      report.error = "重复项";
      errorCount += 1;
    } else {
      seen.add(report.value);
    }
  }
  return { ok: errorCount === 0, values, lines: reports, errorCount };
}

/** list 的 textarea 展示串（一行一项），查看态/进入编辑时使用。 */
export function formatListValue(values: readonly string[]): string {
  return values.join("\n");
}

/** 一次性取某字段「编辑串」：按 kind 把运行时值转成控件可编辑文本。 */
export function formatFieldEditorText(field: FieldDeclaration, value: unknown): string {
  if (field.kind === "json") {
    return formatJsonValue(value);
  }
  if (field.kind === "string_list") {
    return formatListValue(Array.isArray(value) ? value.map(String) : []);
  }
  if (field.kind === "number") {
    return String(value);
  }
  return String(value);
}

/**
 * 行状态徽标推导（C 保存模型核心）：
 * - immediate 字段：变更即提交 committed；与 baseline 不同 → 「已生效」（品牌色系）。
 * - draft 字段：编辑串归一化（合法则解析）后与 committed 不同 → 「待保存」（中性强调）；
 *   保存后 committed 更新、徽标清除；放弃则 draft 回退到 committed。
 *   归一化保证「16000」（编辑串）与 16000（运行时值）不误报为已修改。
 */
export function deriveRowStatus(
  field: FieldDeclaration,
  baselineValue: unknown,
  committedValue: unknown,
  editorValue: unknown,
): RowStatus {
  if (field.saveMode === "immediate") {
    return valuesEqual(committedValue, baselineValue) ? "clean" : "applied";
  }
  if (!valuesEqual(parseDraftValue(field, editorValue), committedValue)) {
    return "pending";
  }
  return "clean";
}

export function valuesEqual(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** 待保存项（保存条计数与确认弹窗文案依据）。 */
export type PendingItem = {
  path: string;
  label: string;
  labelEn: string;
  valid: boolean;
};

export function collectPendingItems(
  fields: readonly FieldDeclaration[],
  baseline: Record<string, unknown>,
  committed: Record<string, unknown>,
  drafts: Record<string, unknown>,
): PendingItem[] {
  const items: PendingItem[] = [];
  for (const field of fields) {
    if (field.saveMode !== "draft") {
      continue;
    }
    const editorValue = drafts[field.path];
    const committedValue = committed[field.path];
    if (valuesEqual(parseDraftValue(field, editorValue), committedValue)) {
      continue;
    }
    items.push({
      path: field.path,
      label: field.label,
      labelEn: field.labelEn,
      valid: isDraftValueValid(field, editorValue),
    });
  }
  void baseline;
  return items;
}

/** 草稿值是否处于可保存形态（json 串可解析、number 文本合法、list 无非法行）。 */
export function isDraftValueValid(field: FieldDeclaration, value: unknown): boolean {
  if (field.kind === "json" && typeof value === "string") {
    return validateJsonText(value).ok;
  }
  if (field.kind === "number" && typeof value === "string") {
    return validateNumberText(value, field).ok;
  }
  if (field.kind === "string_list" && typeof value === "string") {
    return validateListText(value).ok;
  }
  return true;
}

/**
 * 模拟保存：把合法草稿提交为 committed；非法草稿原样保留（保存动作不会吞掉错误）。
 * 返回提交的路径与仍被阻塞的路径。
 */
export function applyDraftSave(
  fields: readonly FieldDeclaration[],
  committed: Record<string, unknown>,
  drafts: Record<string, unknown>,
): { committed: Record<string, unknown>; appliedPaths: string[]; blockedPaths: string[] } {
  const next = { ...committed };
  const appliedPaths: string[] = [];
  const blockedPaths: string[] = [];
  for (const field of fields) {
    if (field.saveMode !== "draft") {
      continue;
    }
    const editorValue = drafts[field.path];
    if (valuesEqual(parseDraftValue(field, editorValue), next[field.path])) {
      continue;
    }
    if (!isDraftValueValid(field, editorValue)) {
      blockedPaths.push(field.path);
      continue;
    }
    next[field.path] = parseDraftValue(field, editorValue);
    appliedPaths.push(field.path);
  }
  return { committed: next, appliedPaths, blockedPaths };
}

/** 把编辑串解析回运行时值（合法前提下：json→对象、number→数值、list→数组）。 */
export function parseDraftValue(field: FieldDeclaration, value: unknown): unknown {
  if (field.kind === "json" && typeof value === "string") {
    const result = validateJsonText(value);
    return result.ok ? result.value : value;
  }
  if (field.kind === "number" && typeof value === "string") {
    const result = validateNumberText(value, field);
    return result.ok ? result.value : value;
  }
  if (field.kind === "string_list" && typeof value === "string") {
    return validateListText(value).values;
  }
  return value;
}
