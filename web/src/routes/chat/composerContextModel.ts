import type { SessionCacheCompositionSegment } from "../../api/types";

export type ComposerContextHitKind = "hit" | "miss" | "never" | "unknown";

export type ComposerContextSegment = {
  key: string;
  name: string;
  tokensLabel: string;
  tokens: number;
  pct: number;
  pctLabel: string;
  /** CSS color for composition bar / legend swatch. */
  color: string;
  hit: ComposerContextHitKind;
  contentPreview?: string;
};

export type ComposerContextCacheState = "observed" | "missing" | "not_called";

export type ComposerContextHitShares = {
  hit: number;
  miss: number;
  never: number;
  unknown: number;
};

export type ComposerContextRingModel = {
  usagePercent: number;
  hitPercent: number;
  usedLabel: string;
  empty: boolean;
  cacheState: ComposerContextCacheState;
  segments: ComposerContextSegment[];
  hitShares: ComposerContextHitShares;
  detailAvailable: boolean;
};

const SEGMENT_COLORS: Record<string, string> = {
  system: "#64748b",
  tools: "#7c3aed",
  rules: "#15803d",
  skills: "#a16207",
  context: "#2563eb",
  dynamic: "#ca8a04",
  turn: "#dc2626",
  other: "#64748b",
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

export function resolveComposerSegmentHitKind(
  segment: Pick<
    SessionCacheCompositionSegment,
    "cachePolicy" | "observedStatus" | "status" | "observedCachedInputTokens" | "observedMissedInputTokens"
  >,
): ComposerContextHitKind {
  const policy = String(segment.cachePolicy ?? "").trim().toLowerCase();
  if (policy.includes("never")) {
    return "never";
  }
  const observed = String(segment.observedStatus ?? "").trim().toLowerCase();
  if (observed.includes("hit") && !observed.includes("miss") && !observed.includes("partial")) {
    return "hit";
  }
  if (observed.includes("miss") && !observed.includes("hit")) {
    return "miss";
  }
  if (observed.includes("partial")) {
    return "miss";
  }
  const status = String(segment.status ?? "").trim().toLowerCase();
  if (status.includes("hit") && !status.includes("miss") && !status.includes("partial")) {
    return "hit";
  }
  if (status.includes("miss") && !status.includes("hit")) {
    return "miss";
  }
  if (status.includes("partial")) {
    return "miss";
  }
  const cached = Math.max(0, segment.observedCachedInputTokens ?? 0);
  const missed = Math.max(0, segment.observedMissedInputTokens ?? 0);
  if (cached > 0 && missed === 0) {
    return "hit";
  }
  if (missed > 0 && cached === 0) {
    return "miss";
  }
  if (policy.includes("volatile") || policy.includes("ephemeral")) {
    return "never";
  }
  return "unknown";
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
  const observed = options.cacheUsageObserved
    ?? ((options.cachedInputTokens ?? 0) > 0 || (options.cacheCreationInputTokens ?? 0) > 0);
  return observed ? "observed" : "missing";
}

export function resolveComposerSegmentColor(
  segment: Pick<SessionCacheCompositionSegment, "key" | "promptCategory">,
): string {
  const key = String(segment.key ?? "").trim().toLowerCase();
  const category = String(segment.promptCategory ?? "").trim().toLowerCase();
  const blob = `${key} ${category}`;
  if (blob.includes("system")) return SEGMENT_COLORS.system;
  if (blob.includes("tool")) return SEGMENT_COLORS.tools;
  if (blob.includes("skill")) return SEGMENT_COLORS.skills;
  if (blob.includes("rule") || blob.includes("protocol") || blob.includes("规范") || blob.includes("guidance")) {
    return SEGMENT_COLORS.rules;
  }
  if (blob.includes("dynamic") || blob.includes("runtime") || blob.includes("volatile")) {
    return SEGMENT_COLORS.dynamic;
  }
  if (
    blob.includes("user")
    || blob.includes("turn")
    || blob.includes("current")
    || blob.includes("input")
    || blob.includes("本轮")
  ) {
    return SEGMENT_COLORS.turn;
  }
  if (blob.includes("history") || blob.includes("context") || blob.includes("message") || blob.includes("会话")) {
    return SEGMENT_COLORS.context;
  }
  return SEGMENT_COLORS.other;
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
  const usageUsed = Math.max(0, options.usageUsed);
  const usageLimit = Math.max(0, options.usageLimit);
  const usagePercent = usageLimit > 0
    ? Math.round(Math.max(0, Math.min(100, (usageUsed / usageLimit) * 100)))
    : 0;
  const hitPercent = Math.round(Math.max(0, Math.min(100, options.hitPercent)));

  const positive = options.segments
    .map((segment) => ({
      ...segment,
      tokens: Math.max(0, segment.tokens ?? 0),
    }))
    .filter((segment) => segment.tokens > 0);
  const totalTokens = positive.reduce((sum, segment) => sum + segment.tokens, 0);
  const segments: ComposerContextSegment[] = totalTokens > 0
    ? positive.map((segment) => {
      const pct = Math.round((segment.tokens / totalTokens) * 1000) / 10;
      const contentPreview = String(segment.contentPreview ?? "").trim();
      return {
        key: segment.key || segment.label || "segment",
        name: String(segment.label || segment.key || (options.lang === "zh" ? "分段" : "Segment")).trim(),
        tokens: segment.tokens,
        tokensLabel: formatCompactTokenCount(segment.tokens),
        pct,
        pctLabel: `${pct}%`,
        color: resolveComposerSegmentColor(segment),
        hit: resolveComposerSegmentHitKind(segment),
        ...(contentPreview ? { contentPreview } : {}),
      };
    })
    : [];

  const hitShares = segments.reduce<ComposerContextHitShares>((shares, segment) => {
    shares[segment.hit] += segment.pct;
    return shares;
  }, { hit: 0, miss: 0, never: 0, unknown: 0 });

  const empty = segments.length === 0 && usagePercent === 0;
  const usedLabel = usageLimit > 0
    ? `${formatCompactTokenCount(usageUsed)} / ${formatCompactTokenCount(usageLimit)}`
    : (options.lang === "zh" ? "-- / --" : "-- / --");

  return {
    usagePercent,
    hitPercent,
    usedLabel,
    empty,
    cacheState: resolveComposerCacheState(options),
    segments,
    hitShares,
    detailAvailable: Boolean(options.detailAvailable),
  };
}
