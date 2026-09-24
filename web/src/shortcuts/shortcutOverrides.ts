/**
 * 用户覆盖的静默持久化（localStorage）。键名沿用 `vibelution.` 前缀惯例。
 * 设置页改键 UI 属后续任务；本轮只提供读/写/清洗三个纯入口。
 * 存储形状：`Record<commandId, string[]>`（整组替换；显式空数组 = 用户清除）。
 */
import type { ShortcutOverrides } from "./commands";
import { SHORTCUT_COMMANDS } from "./commands";
import { parseShortcutBinding } from "./bindingFormat";

export const SHORTCUT_OVERRIDES_STORAGE_KEY = "vibelution.shortcuts.overrides";

type OverridesStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function browserStorage(): OverridesStorage | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage;
}

/**
 * 清洗任意解析出的 JSON 为合法覆盖表：
 * - 只保留已知命令 ID；绑定条目非法的整组按缺失处理（回退默认）；
 * - 显式空数组保留（= 用户清除，不回退默认）。
 */
export function normalizeShortcutOverrides(value: unknown): ShortcutOverrides {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return {};
  }
  const source = value as Record<string, unknown>;
  const knownIds = new Set(SHORTCUT_COMMANDS.map((entry) => entry.id as string));
  const result: Record<string, readonly string[]> = {};
  for (const [id, raw] of Object.entries(source)) {
    if (!knownIds.has(id) || !Array.isArray(raw)) {
      continue;
    }
    const bindings = raw
      .filter((binding): binding is string => typeof binding === "string")
      .filter((binding) => parseShortcutBinding(binding) !== null);
    if (bindings.length !== raw.length && raw.length > 0) {
      // 有非法条目：按整组无效处理（与生效表「全部非法回退默认」一致）。
      continue;
    }
    result[id] = bindings;
  }
  return result;
}

export function readStoredShortcutOverrides(
  storage: OverridesStorage | null = browserStorage(),
): ShortcutOverrides {
  if (!storage) {
    return {};
  }
  let raw: string | null = null;
  try {
    raw = storage.getItem(SHORTCUT_OVERRIDES_STORAGE_KEY);
  } catch {
    return {};
  }
  if (!raw) {
    return {};
  }
  try {
    return normalizeShortcutOverrides(JSON.parse(raw));
  } catch {
    return {};
  }
}

export function writeStoredShortcutOverrides(
  overrides: ShortcutOverrides,
  storage: OverridesStorage | null = browserStorage(),
): void {
  if (!storage) {
    return;
  }
  try {
    const hasEntries = Object.keys(overrides).length > 0;
    if (hasEntries) {
      storage.setItem(SHORTCUT_OVERRIDES_STORAGE_KEY, JSON.stringify(overrides));
    } else {
      storage.removeItem(SHORTCUT_OVERRIDES_STORAGE_KEY);
    }
  } catch {
    // 存储不可写（隐私模式/配额）时静默降级为会话内覆盖。
  }
}
