/**
 * 设置页集中式导航意图模块（ZCode settingsNavigation 模式对齐）。
 *
 * 三个生产入口统一经此模块跳设置页：
 * - 设置搜索选中（configSettingsSearch 命中 → requestSettingsFocus）；
 * - 命令面板的 config 导航命令（GlobalCommandSurfaces）；
 * - 历史 URL 入口（?section/?page/?focus 参数继续可用，优先级最高）。
 *
 * 语义：
 * - requestSettingsFocus 把意图暂存 sessionStorage 并广播 CustomEvent：
 *   已打开的设置页即时热切换；未打开时意图留存，下次设置页挂载时消费并清除。
 * - 「上次停留分区」记忆（localStorage）：打开设置页默认停在上次分区；
 *   首次进入（无记忆）保持现状默认（总览/默认组），不改变既有行为。
 * - 落地优先级：显式 URL > 意图 > 上次停留 > 默认。
 *
 * 本模块只做存储/广播/裁决，不理解 settingsGroups 结构；组/页合法性由
 * 消费方（ConfigRoute）解析。SSR/测试安全：访问缺失的 Web 存储时静默降级。
 */

export type SettingsFocusTarget = {
  /** 设置大组（ConfigSettingsGroupId，消费方校验合法性）。 */
  groupId?: string;
  /** 组内页面 id。 */
  pageId?: string;
  /** 目标分区（toml 编辑器分区 id）。 */
  sectionId?: string;
  /** 目标叶子字段的绝对配置路径（如 ui.workbench_theme）。 */
  fieldId?: string;
};

export type SettingsFocusSource = "url" | "intent" | "last" | "default";

export type ResolvedSettingsEntry = {
  groupId: string;
  pageId: string;
  sectionId: string;
  fieldId: string;
  source: SettingsFocusSource;
};

/** 意图广播事件名（CustomEvent，detail = SettingsFocusTarget）。 */
export const SETTINGS_FOCUS_INTENT_EVENT = "vibelution:settings-focus-intent";

/** sessionStorage 意图暂存键（一次性，消费即清除）。 */
export const SETTINGS_FOCUS_INTENT_STORAGE_KEY = "vibelution.settings.focus-intent.v1";

/** localStorage「上次停留分区」键。 */
export const SETTINGS_LAST_SECTION_STORAGE_KEY = "vibelution.settings.last-section.v1";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  return typeof value === "string" ? value.trim() : "";
}

function parseTarget(raw: string | null): SettingsFocusTarget | null {
  if (!raw) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed)) {
      return null;
    }
    const target: SettingsFocusTarget = {
      groupId: readString(parsed, "groupId"),
      pageId: readString(parsed, "pageId"),
      sectionId: readString(parsed, "sectionId"),
      fieldId: readString(parsed, "fieldId"),
    };
    return target.groupId || target.pageId || target.sectionId || target.fieldId ? target : null;
  } catch {
    return null;
  }
}

function safeSessionStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

function safeLocalStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

/** 暂存聚焦意图并广播：已打开的设置页即时热切换，未打开则留存到下次挂载。 */
export function requestSettingsFocus(target: SettingsFocusTarget): void {
  const payload = JSON.stringify({
    groupId: target.groupId ?? "",
    pageId: target.pageId ?? "",
    sectionId: target.sectionId ?? "",
    fieldId: target.fieldId ?? "",
  });
  safeSessionStorage()?.setItem(SETTINGS_FOCUS_INTENT_STORAGE_KEY, payload);
  if (typeof window !== "undefined" && typeof window.CustomEvent === "function") {
    window.dispatchEvent(new CustomEvent<SettingsFocusTarget>(SETTINGS_FOCUS_INTENT_EVENT, { detail: target }));
  }
}

/** 读取当前意图（不清除）。 */
export function peekSettingsFocusIntent(): SettingsFocusTarget | null {
  return parseTarget(safeSessionStorage()?.getItem(SETTINGS_FOCUS_INTENT_STORAGE_KEY) ?? null);
}

/** 消费并清除意图（一次性）。 */
export function consumeSettingsFocusIntent(): SettingsFocusTarget | null {
  const storage = safeSessionStorage();
  const target = peekSettingsFocusIntent();
  try {
    storage?.removeItem(SETTINGS_FOCUS_INTENT_STORAGE_KEY);
  } catch {
    // 存储不可用时意图自然失效。
  }
  return target;
}

/** 订阅意图广播（已打开设置页的热切换）；返回退订函数。 */
export function subscribeSettingsFocus(listener: (target: SettingsFocusTarget) => void): () => void {
  if (typeof window === "undefined") {
    return () => undefined;
  }
  const handler = (event: Event) => {
    const detail = (event as CustomEvent<SettingsFocusTarget>).detail;
    if (isRecord(detail) || typeof detail === "object") {
      listener((detail ?? {}) as SettingsFocusTarget);
    }
  };
  window.addEventListener(SETTINGS_FOCUS_INTENT_EVENT, handler);
  return () => window.removeEventListener(SETTINGS_FOCUS_INTENT_EVENT, handler);
}

/** 读「上次停留分区」；无记忆或损坏时返回 null。 */
export function readLastSettingsLocation(): { groupId: string; pageId: string } | null {
  const parsed = parseTarget(safeLocalStorage()?.getItem(SETTINGS_LAST_SECTION_STORAGE_KEY) ?? null);
  if (!parsed?.groupId) {
    return null;
  }
  return { groupId: parsed.groupId, pageId: parsed.pageId ?? "" };
}

/** 写「上次停留分区」（groupId 必填，pageId 可空）。 */
export function writeLastSettingsLocation(location: { groupId: string; pageId?: string }): void {
  if (!location.groupId.trim()) {
    return;
  }
  safeLocalStorage()?.setItem(
    SETTINGS_LAST_SECTION_STORAGE_KEY,
    JSON.stringify({ groupId: location.groupId.trim(), pageId: (location.pageId ?? "").trim() }),
  );
}

/**
 * 设置页挂载时的入口裁决：显式 URL > 意图 > 上次停留 > 默认。
 * - URL 分支不消费意图（URL 显式表达优先，意图留存到无 URL 目标的下一次进入）；
 * - 命中意图时清除意图（一次性）；
 * - default 分支返回空串，由消费方保持现状默认行为（resolveConfigSettingsSelection）。
 */
export function resolveSettingsEntry(input: {
  urlGroupId: string;
  urlPageId: string;
  urlSectionId: string;
  urlFieldId: string;
}): ResolvedSettingsEntry {
  if (input.urlGroupId || input.urlPageId || input.urlSectionId || input.urlFieldId) {
    return {
      groupId: input.urlGroupId,
      pageId: input.urlPageId,
      sectionId: input.urlSectionId,
      fieldId: input.urlFieldId,
      source: "url",
    };
  }
  const intent = consumeSettingsFocusIntent();
  if (intent) {
    return {
      groupId: intent.groupId ?? "",
      pageId: intent.pageId ?? "",
      sectionId: intent.sectionId ?? "",
      fieldId: intent.fieldId ?? "",
      source: "intent",
    };
  }
  const last = readLastSettingsLocation();
  if (last) {
    return { groupId: last.groupId, pageId: last.pageId, sectionId: "", fieldId: "", source: "last" };
  }
  return { groupId: "", pageId: "", sectionId: "", fieldId: "", source: "default" };
}

// ============================================================================
// 分区内容 ready 信号：聚焦意图的落地等待（替代旧的 60 帧 rAF 轮询）。
// 分区编辑器挂载或行可见性（展开/高级层/嵌套层）变化后发脉冲；设置页落地
// 执行器收到脉冲后重放一次聚焦尝试，成功即收口。
// ============================================================================

let settingsContentReadyNotifier: (() => void) | null = null;

/** 设置分区内容 ready 脉冲（渲染层在挂载/展开变化后调用）。 */
export function notifySettingsContentReady(): void {
  settingsContentReadyNotifier?.();
}

/** 注册 ready 监听（设置页落地执行器）；返回退订函数。 */
export function onSettingsContentReady(notifier: () => void): () => void {
  settingsContentReadyNotifier = notifier;
  return () => {
    if (settingsContentReadyNotifier === notifier) {
      settingsContentReadyNotifier = null;
    }
  };
}
