/**
 * 界面字号偏好（localStorage，仅本机）。单一派生基准 --vui-font-base 的用户
 * 轨道：只写 CSS 变量，不动根 font-size（web/index.html 防闪 IIFE 同点早挂）。
 * 存储键沿用 `vibelution.` 前缀惯例；合法域为整数 14–18px（默认 16）。
 * normalize 口径：非法或越界的存量值一律回默认 16（诚实回退，不静默钳到边界）；
 * 步进器输入的越界值走 clampUiFontBasePx（钳进 14–18）。
 * 设置页改数面板是 routes/ConfigUiFontSettings.tsx；行上标注了本地偏好语义
 * （不进 config.toml，照 ConfigShortcutsPanel 的本地持久化先例）。
 */
export const UI_FONT_BASE_STORAGE_KEY = "vibelution.workbench.font-base-px";
export const UI_FONT_BASE_CSS_PROPERTY = "--vui-font-base";
export const DEFAULT_UI_FONT_BASE_PX = 16;
export const MIN_UI_FONT_BASE_PX = 14;
export const MAX_UI_FONT_BASE_PX = 18;

type UiFontStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;
type UiFontDocumentTarget = Pick<Document, "documentElement">;

function browserStorage(): UiFontStorage | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage;
}

/**
 * 清洗任意存量值为合法基准字号：整数且在 [14,18] 内原样保留；
 * 其余（非数、小数、越界、空）一律回默认 16。
 */
export function normalizeUiFontBasePx(value: unknown): number {
  const parsed = typeof value === "number"
    ? value
    : typeof value === "string" && value.trim() !== "" ? Number(value) : Number.NaN;
  if (!Number.isInteger(parsed)) {
    return DEFAULT_UI_FONT_BASE_PX;
  }
  if (parsed < MIN_UI_FONT_BASE_PX || parsed > MAX_UI_FONT_BASE_PX) {
    return DEFAULT_UI_FONT_BASE_PX;
  }
  return parsed;
}

/** 步进器输入口径：任意数值钳进 [14,18] 并取整。 */
export function clampUiFontBasePx(value: number): number {
  if (!Number.isFinite(value)) {
    return DEFAULT_UI_FONT_BASE_PX;
  }
  return Math.min(MAX_UI_FONT_BASE_PX, Math.max(MIN_UI_FONT_BASE_PX, Math.round(value)));
}

export function readStoredUiFontBasePx(storage: UiFontStorage | null = browserStorage()): number {
  if (!storage) {
    return DEFAULT_UI_FONT_BASE_PX;
  }
  let raw: string | null = null;
  try {
    raw = storage.getItem(UI_FONT_BASE_STORAGE_KEY);
  } catch {
    return DEFAULT_UI_FONT_BASE_PX;
  }
  if (raw === null) {
    return DEFAULT_UI_FONT_BASE_PX;
  }
  return normalizeUiFontBasePx(raw);
}

type UiFontBaseListener = (px: number) => void;

const changeListeners = new Set<UiFontBaseListener>();

function notifyUiFontBaseChanged(px: number): void {
  for (const listener of [...changeListeners]) {
    listener(px);
  }
}

function handleStorageEvent(event: StorageEvent): void {
  // key === null 表示 clear()，同样按「重读当前值」处理。
  if (event.key !== null && event.key !== UI_FONT_BASE_STORAGE_KEY) {
    return;
  }
  notifyUiFontBaseChanged(readStoredUiFontBasePx());
}

/**
 * 订阅基准字号变更（本窗口写入 + 其他窗口 storage 事件）。返回取消订阅函数。
 * 订阅方据此即时 setProperty，设置页改数无需刷新。
 */
export function subscribeStoredUiFontBasePx(listener: UiFontBaseListener): () => void {
  if (changeListeners.size === 0 && typeof window !== "undefined") {
    window.addEventListener("storage", handleStorageEvent);
  }
  changeListeners.add(listener);
  return () => {
    changeListeners.delete(listener);
    if (changeListeners.size === 0 && typeof window !== "undefined") {
      window.removeEventListener("storage", handleStorageEvent);
    }
  };
}

/** 把基准字号写到文档根的 --vui-font-base（px）。只动这一个变量，不碰根 font-size。 */
export function applyUiFontBasePx(target: UiFontDocumentTarget, px: number): void {
  target.documentElement.style.setProperty(UI_FONT_BASE_CSS_PROPERTY, `${normalizeUiFontBasePx(px)}px`);
}

/**
 * 写入偏好并通知订阅者；与已存值一致时跳过写入与通知（幂等）。
 * 默认值 16 移除存储键（缺省 = 默认，与早挂 IIFE 的「未设置则不动」一致）。
 * 存储不可写（隐私模式/配额）时静默降级为会话内覆盖。
 */
export function writeStoredUiFontBasePx(
  px: number,
  storage: UiFontStorage | null = browserStorage(),
): number {
  const normalized = normalizeUiFontBasePx(px);
  if (!storage) {
    return normalized;
  }
  try {
    const serialized = normalized === DEFAULT_UI_FONT_BASE_PX ? null : String(normalized);
    if (storage.getItem(UI_FONT_BASE_STORAGE_KEY) === serialized) {
      return normalized;
    }
    if (serialized === null) {
      storage.removeItem(UI_FONT_BASE_STORAGE_KEY);
    } else {
      storage.setItem(UI_FONT_BASE_STORAGE_KEY, serialized);
    }
    notifyUiFontBaseChanged(normalized);
  } catch {
    // 存储不可写：保持会话内生效。
  }
  return normalized;
}
