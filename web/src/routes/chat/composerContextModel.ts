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
export type ComposerContextRingModel = {
  usagePercent: number;
  usageLabel: string;
  remainingLabel: string;
  capacityKnown: boolean;
  hitPercent: number;
  usedLabel: string;
  empty: boolean;
  cacheState: ComposerContextCacheState;
  segments: ComposerContextSegment[];
  groups: ComposerContextGroup[];
  detailAvailable: boolean;
};

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
    segments,
    groups,
    detailAvailable: options.detailAvailable,
  };
}
