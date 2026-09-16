import type { SessionCacheCompositionSegment } from "../../api/types";

export type ComposerContextSegment = {
  key: string;
  name: string;
  tokens: number;
  tokensLabel: string;
  pctLabel: string;
  contentPreview?: string;
};
export type ComposerContextGroup = {
  key: string;
  name: string;
  tokensLabel: string;
  segments: ComposerContextSegment[];
};
export type ComposerContextCacheState = "observed" | "missing" | "not_called";
/** Claude Code-paradigm indicator: shown only when little room remains before auto-compression. */
export type ComposerContextAutoCompact = {
  remainingPercent: number;
  remainingTokens: number;
  remainingTokensLabel: string;
  thresholdPercent: number;
  thresholdTokens: number;
};
export type ComposerContextRingModel = {
  usagePercent: number;
  usageLabel: string;
  remainingLabel: string;
  capacityKnown: boolean;
  hitPercent: number;
  usedLabel: string;
  empty: boolean;
  cacheState: ComposerContextCacheState;
  /** Compact absolute cached-token label for the observed cache state (e.g. "83K"). */
  cachedTokensLabel: string;
  /** Provider-derived generation speed for the last call; null when unmeasurable. */
  generationTokensPerSecond: number | null;
  /** Non-null only when remaining room before auto-compression drops below 40%. */
  autoCompact: ComposerContextAutoCompact | null;
  segments: ComposerContextSegment[];
  groups: ComposerContextGroup[];
  detailAvailable: boolean;
};

/** Only surface the auto-compression countdown once little room is left (Claude Code paradigm). */
export const AUTO_COMPACT_VISIBLE_REMAINING_PERCENT = 40;

export function formatCompactTokenCount(value: number): string {
  const n = Math.max(0, Math.round(value));
  if (n >= 1_000_000) {
    const scaled = n / 1_000_000;
    return `${scaled >= 10 ? scaled.toFixed(0) : scaled.toFixed(1).replace(/\.0$/, "")}M`;
  }
  if (n >= 1000) {
    const scaled = n / 1000;
    return `${scaled >= 10 ? scaled.toFixed(0) : scaled.toFixed(1).replace(/\.0$/, "")}K`;
  }
  return String(n);
}

/** Compact one-decimal tok/s label (45 → "45", 45.34 → "45.3"). */
export function formatTokensPerSecondValue(value: number): string {
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
}

export function resolveComposerCacheState(options: {
  cacheSource?: string;
  cacheUsageObserved?: boolean;
  cachedInputTokens?: number;
  cacheCreationInputTokens?: number;
}): ComposerContextCacheState {
  const source = String(options.cacheSource ?? "").trim();
  if (source === "not_called") {
    return "not_called";
  }
  if (source !== "provider_usage") {
    return "missing";
  }
  const observed =
    options.cacheUsageObserved ??
    ((options.cachedInputTokens ?? 0) > 0 ||
      (options.cacheCreationInputTokens ?? 0) > 0);
  return observed ? "observed" : "missing";
}

const PROMPT_KEYS = new Set([
  "system_prompt",
  "system_prompt_overhead",
  "system_cache_prefix",
  "agent_protocol",
  "agent_runtime",
  "prompt_template",
  "agent_prompt_snapshot",
  "project_rules",
]);
function groupKey(segment: SessionCacheCompositionSegment): string {
  if (segment.key === "history" || segment.promptCategory === "history")
    return "history";
  if (
    PROMPT_KEYS.has(segment.key) ||
    segment.promptCategory === "system_prompt"
  )
    return "prompt";
  return "other";
}

export function buildComposerContextRingModel(options: {
  usageUsed: number;
  usageLimit: number;
  hitPercent: number;
  detailAvailable: boolean;
  segments: SessionCacheCompositionSegment[];
  lang: "zh" | "en";
  cacheSource?: string;
  cacheUsageObserved?: boolean;
  cachedInputTokens?: number;
  cacheCreationInputTokens?: number;
  /** Backend-owned first auto-compression level threshold in tokens (read-only). */
  autoCompactThresholdTokens?: number;
  autoCompactEnabled?: boolean;
  /** Provider-derived generation speed for the last call; null when unmeasurable. */
  tokensPerSecond?: number | null;
}): ComposerContextRingModel {
  const used = Math.max(0, options.usageUsed);
  const limit = Math.max(0, options.usageLimit);
  const capacityKnown = limit > 0;
  const usagePercent = capacityKnown ? Math.min(100, (used / limit) * 100) : 0;
  const percentLabel = (value: number) =>
    value > 0 && value < 1 ? "<1%" : `${Math.round(value)}%`;
  const positive = options.segments.filter(
    (segment) => segment.tokens > 0 && segment.key !== "computed_missing",
  );
  const total = positive.reduce((sum, segment) => sum + segment.tokens, 0);
  const segments = positive.map((segment) => {
    const pct = (segment.tokens / total) * 100;
    return {
      key: segment.key,
      name: segment.label || segment.key,
      tokens: segment.tokens,
      tokensLabel: formatCompactTokenCount(segment.tokens),
      pctLabel: pct < 0.1 ? "<0.1%" : `${Math.round(pct * 10) / 10}%`,
      ...(segment.contentPreview
        ? { contentPreview: segment.contentPreview }
        : {}),
    };
  });
  const labels =
    options.lang === "zh"
      ? { history: "对话历史", prompt: "Agent 提示与规范", other: "其他内容" }
      : {
          history: "Conversation history",
          prompt: "Agent prompts & rules",
          other: "Other content",
        };
  const groups = Object.entries(labels).flatMap(([key, name]) => {
    const members = segments.filter(
      (_, index) => groupKey(positive[index]) === key,
    );
    return members.length
      ? [
          {
            key,
            name,
            segments: members,
            tokensLabel: formatCompactTokenCount(
              members.reduce((sum, segment) => sum + segment.tokens, 0),
            ),
          },
        ]
      : [];
  });
  const cacheState = resolveComposerCacheState(options);
  const cachedTokensLabel =
    cacheState === "observed"
      ? formatCompactTokenCount(Math.max(0, options.cachedInputTokens ?? 0))
      : "";
  const autoCompact = resolveAutoCompact({
    used,
    limit,
    capacityKnown,
    autoCompactEnabled: options.autoCompactEnabled,
    autoCompactThresholdTokens: options.autoCompactThresholdTokens,
  });
  return {
    usagePercent,
    usageLabel: capacityKnown ? percentLabel(usagePercent) : "—",
    remainingLabel: percentLabel(100 - usagePercent),
    capacityKnown,
    hitPercent:
      cacheState === "observed"
        ? Math.round(Math.max(0, Math.min(100, options.hitPercent)))
        : 0,
    usedLabel: `${formatCompactTokenCount(used)} / ${capacityKnown ? formatCompactTokenCount(limit) : "—"}`,
    empty: used === 0 && !segments.length && !capacityKnown,
    cacheState,
    cachedTokensLabel,
    generationTokensPerSecond:
      typeof options.tokensPerSecond === "number"
        && Number.isFinite(options.tokensPerSecond)
        && options.tokensPerSecond > 0
        ? options.tokensPerSecond
        : null,
    autoCompact,
    segments,
    groups,
    detailAvailable: options.detailAvailable,
  };
}

function resolveAutoCompact(options: {
  used: number;
  limit: number;
  capacityKnown: boolean;
  autoCompactEnabled?: boolean;
  autoCompactThresholdTokens?: number;
}): ComposerContextAutoCompact | null {
  if (options.autoCompactEnabled === false || !options.capacityKnown) {
    return null;
  }
  const thresholdTokens = Math.max(0, Math.round(options.autoCompactThresholdTokens ?? 0));
  if (thresholdTokens <= 0) {
    return null;
  }
  const remainingTokens = Math.max(0, thresholdTokens - Math.max(0, options.used));
  const remainingPercent = Math.max(
    0,
    Math.min(100, (remainingTokens / Math.max(1, options.limit)) * 100),
  );
  // Claude Code paradigm: avoid permanent noise; only appear below 40%.
  if (remainingPercent >= AUTO_COMPACT_VISIBLE_REMAINING_PERCENT) {
    return null;
  }
  return {
    remainingPercent: Math.round(remainingPercent),
    remainingTokens,
    remainingTokensLabel: formatCompactTokenCount(remainingTokens),
    thresholdPercent: Math.round(
      Math.min(100, (thresholdTokens / Math.max(1, options.limit)) * 100),
    ),
    thresholdTokens,
  };
}
