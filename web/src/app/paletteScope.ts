/**
 * 全局命令面板的 scope 前缀分流 + 最近使用（MRU）纯逻辑。
 *
 * 借鉴 VS Code / Zed 的前缀模式：`#` 进入会话搜索、`>` 只看命令、无前缀
 * 保持现有混合行为。前缀解析、命令过滤与 MRU 记录收敛在这里，挂载面
 * （GlobalCommandSurfaces）只做装配；VCommandPalette 保持数据驱动。
 */

export type PaletteScope =
  | { kind: "default"; text: string }
  | { kind: "sessions"; text: string }
  | { kind: "commands"; text: string };

/** 会话搜索前缀：去掉后交给 useSessionSearchQuery 的 server 分页结果。 */
export const SESSION_SCOPE_PREFIX = "#";
/** 命令模式前缀：只显示命令类条目（导航条目被过滤）。 */
export const COMMAND_SCOPE_PREFIX = ">";

/** 解析面板查询的 scope；`text` 是去前缀后的匹配文本。 */
export function resolvePaletteScope(query: string): PaletteScope {
  if (query.startsWith(SESSION_SCOPE_PREFIX)) {
    return { kind: "sessions", text: query.slice(SESSION_SCOPE_PREFIX.length) };
  }
  if (query.startsWith(COMMAND_SCOPE_PREFIX)) {
    return { kind: "commands", text: query.slice(COMMAND_SCOPE_PREFIX.length) };
  }
  return { kind: "default", text: query };
}

/** 导航条目的 id 命名空间（`nav:...`）；`>` 命令模式会过滤掉它们。 */
export const NAV_ITEM_ID_PREFIX = "nav:";

export function isCommandItem(item: { id: string }): boolean {
  return !item.id.startsWith(NAV_ITEM_ID_PREFIX);
}

/**
 * 注入「最近使用」分组并置顶：命中的条目复制到顶部分组并从原分组移除
 * （去重置顶，视觉不重复、React key 不冲突）；无命中时保持原样。
 * MRU 顺序 = 最近执行在前。
 */
export function withRecentGroupTop<T extends { id: string; group: string }>(
  items: readonly T[],
  recentIds: readonly string[],
  groupLabel: string,
): T[] {
  if (items.length === 0 || recentIds.length === 0) {
    return [...items];
  }
  const byId = new Map(items.map((item) => [item.id, item]));
  const movedIds = new Set<string>();
  const recentItems: T[] = [];
  for (const id of new Set(recentIds)) {
    const item = byId.get(id);
    if (!item) continue;
    movedIds.add(id);
    recentItems.push({ ...item, group: groupLabel });
  }
  if (recentItems.length === 0) {
    return [...items];
  }
  return [...recentItems, ...items.filter((item) => !movedIds.has(item.id))];
}

export const COMMAND_PALETTE_RECENT_STORAGE_KEY = "vibelution.commandPalette.recent.v1";
export const COMMAND_PALETTE_RECENT_LIMIT = 20;

type RecentStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function browserStorage(): RecentStorage | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage;
}

export function normalizeRecentCommandIds(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((entry): entry is string => typeof entry === "string");
}

export function readRecentCommandIds(
  storage: RecentStorage | null = browserStorage(),
): string[] {
  if (!storage) {
    return [];
  }
  let raw: string | null = null;
  try {
    raw = storage.getItem(COMMAND_PALETTE_RECENT_STORAGE_KEY);
  } catch {
    return [];
  }
  if (!raw) {
    return [];
  }
  try {
    return normalizeRecentCommandIds(JSON.parse(raw));
  } catch {
    return [];
  }
}

/**
 * 记录一次执行：id 移到最前（去重）、截断到上限并持久化到 localStorage
 * （全局单键；面板挂载面没有现成的 workspace id，不为此引入）。
 * 返回新列表供 React state 同步；存储不可写时仍返回计算结果（会话内降级）。
 */
export function recordRecentCommandId(
  id: string,
  previous: readonly string[],
  storage: RecentStorage | null = browserStorage(),
): string[] {
  const next = [id, ...previous.filter((entry) => entry !== id)].slice(0, COMMAND_PALETTE_RECENT_LIMIT);
  if (storage) {
    try {
      storage.setItem(COMMAND_PALETTE_RECENT_STORAGE_KEY, JSON.stringify(next));
    } catch {
      // 存储不可写（隐私模式/配额）时静默降级为会话内记录。
    }
  }
  return next;
}
