/** Session-level Turn Status Bar tail composition (model-injectable blocks). */

export const TURN_STATUS_TAIL_STORAGE_PREFIX = "vibelution.chat.turnStatusTail.";

export type TurnStatusTailBlockId =
  | "budget"
  | "clock"
  | "git_brief"
  | "git_paths"
  | "run_digest"
  | "cache_hint"
  | "identity";

export type TurnStatusTailBlocks = Record<TurnStatusTailBlockId, boolean>;

export type TurnStatusTailLimits = {
  gitPathsMax: number;
  runDigestToolsMax: number;
  maxTailChars: number;
};

export type TurnStatusTailConfig = {
  version: 1;
  enabled: boolean;
  blocks: TurnStatusTailBlocks;
  limits: TurnStatusTailLimits;
};

export const TURN_STATUS_TAIL_BLOCK_META: Array<{
  id: TurnStatusTailBlockId;
  zh: string;
  en: string;
  hintZh: string;
  hintEn: string;
  defaultOn: boolean;
}> = [
  {
    id: "budget",
    zh: "工具预算 / 迭代",
    en: "Tool budget / iteration",
    hintZh: "used/max/remaining 与 budget_status（默认开）",
    hintEn: "used/max/remaining and budget_status (on by default)",
    defaultOn: true,
  },
  {
    id: "clock",
    zh: "本地时间",
    en: "Local clock",
    hintZh: "时区 + ISO 时间（默认开）",
    hintEn: "Timezone + ISO time (on by default)",
    defaultOn: true,
  },
  {
    id: "git_brief",
    zh: "Git 简报",
    en: "Git brief",
    hintZh: "分支 / dirty / ahead-behind（默认关）",
    hintEn: "branch / dirty / ahead-behind (off by default)",
    defaultOn: false,
  },
  {
    id: "git_paths",
    zh: "变更路径",
    en: "Changed paths",
    hintZh: "路径列表，默认最多 12 条（非全文 diff）",
    hintEn: "Path list, max 12 by default (not full diff)",
    defaultOn: false,
  },
  {
    id: "run_digest",
    zh: "最近工具 / 任务",
    en: "Run digest",
    hintZh: "本回合任务一句 + 最近工具名",
    hintEn: "One-line task + recent tool names",
    defaultOn: false,
  },
  {
    id: "cache_hint",
    zh: "缓存读写下标",
    en: "Cache hint",
    hintZh: "本步 prompt-cache 读/写/未缓存（有 usage 时）",
    hintEn: "cache read/write/uncached tokens when available",
    defaultOn: false,
  },
  {
    id: "identity",
    zh: "会话 / worktree 身份",
    en: "Session / worktree id",
    hintZh: "session 短码、agentId",
    hintEn: "short session id and agentId",
    defaultOn: false,
  },
];

export function defaultTurnStatusTailConfig(): TurnStatusTailConfig {
  const blocks = Object.fromEntries(
    TURN_STATUS_TAIL_BLOCK_META.map((item) => [item.id, item.defaultOn]),
  ) as TurnStatusTailBlocks;
  return {
    version: 1,
    enabled: true,
    blocks,
    limits: {
      gitPathsMax: 12,
      runDigestToolsMax: 8,
      maxTailChars: 2500,
    },
  };
}

export function normalizeTurnStatusTailConfig(raw: unknown): TurnStatusTailConfig {
  const base = defaultTurnStatusTailConfig();
  if (!raw || typeof raw !== "object") {
    return base;
  }
  const value = raw as Record<string, unknown>;
  const blocksRaw =
    value.blocks && typeof value.blocks === "object"
      ? (value.blocks as Record<string, unknown>)
      : {};
  const limitsRaw =
    value.limits && typeof value.limits === "object"
      ? (value.limits as Record<string, unknown>)
      : {};
  const blocks = { ...base.blocks };
  for (const item of TURN_STATUS_TAIL_BLOCK_META) {
    if (typeof blocksRaw[item.id] === "boolean") {
      blocks[item.id] = blocksRaw[item.id] as boolean;
    }
  }
  const clamp = (n: unknown, fallback: number, min: number, max: number) => {
    const parsed = Number(n);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.max(min, Math.min(max, Math.floor(parsed)));
  };
  return {
    version: 1,
    enabled: value.enabled === false ? false : true,
    blocks,
    limits: {
      gitPathsMax: clamp(limitsRaw.gitPathsMax, base.limits.gitPathsMax, 1, 40),
      runDigestToolsMax: clamp(limitsRaw.runDigestToolsMax, base.limits.runDigestToolsMax, 1, 24),
      maxTailChars: clamp(limitsRaw.maxTailChars, base.limits.maxTailChars, 400, 12000),
    },
  };
}

export function turnStatusTailStorageKey(sessionId: string): string {
  return `${TURN_STATUS_TAIL_STORAGE_PREFIX}${String(sessionId || "").trim() || "default"}`;
}

export function loadTurnStatusTailConfig(sessionId: string): TurnStatusTailConfig {
  if (typeof window === "undefined") {
    return defaultTurnStatusTailConfig();
  }
  try {
    const raw = window.localStorage.getItem(turnStatusTailStorageKey(sessionId));
    if (!raw) {
      return defaultTurnStatusTailConfig();
    }
    return normalizeTurnStatusTailConfig(JSON.parse(raw));
  } catch {
    return defaultTurnStatusTailConfig();
  }
}

export function saveTurnStatusTailConfig(sessionId: string, config: TurnStatusTailConfig): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(
      turnStatusTailStorageKey(sessionId),
      JSON.stringify(normalizeTurnStatusTailConfig(config)),
    );
  } catch {
    // ignore quota / private mode
  }
}

export function estimateTurnStatusTailRisk(
  config: TurnStatusTailConfig,
  lang: "zh" | "en",
): { level: "low" | "medium"; label: string } {
  const normalized = normalizeTurnStatusTailConfig(config);
  if (!normalized.enabled) {
    return { level: "low", label: lang === "zh" ? "未注入" : "Not injected" };
  }
  const heavy =
    normalized.blocks.git_paths || normalized.blocks.git_brief || normalized.blocks.run_digest;
  if (heavy) {
    return { level: "medium", label: lang === "zh" ? "中（含 git/摘要）" : "Medium (git/digest)" };
  }
  return { level: "low", label: lang === "zh" ? "低" : "Low" };
}
