import type { SessionCacheCompositionSegment, SessionDetail } from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionary";
import {
  buildCacheDonutSegments,
  type SessionCacheCompositionDiagnostics,
} from "./sessionCacheComposition";
import { cacheCalibrationSummaryLabel, promptSegmentDisplayLabel } from "./chatRoutePresentation";
import type { CacheDonutSegment } from "./CacheDetailDialog";

export type ChatCacheDetailViewModel = {
  providerCacheInputTokens: number;
  providerCachedInputTokens: number;
  providerUncachedInputTokens: number;
  cacheCalibrationStatus: string;
  cacheCalibrationReason: string;
  cacheComputedOverestimatedInputTokens: number;
  cacheProviderExtraCachedInputTokens: number;
  cacheCalibrationSummaryText: string;
  trueCacheDonutSegments: CacheDonutSegment[];
  computedCacheCompositionSegments: SessionCacheCompositionSegment[];
  computedCacheCompositionTotalTokens: number;
  upperBoundCacheInputTokens: number;
  upperBoundCachedInputTokens: number;
  upperBoundCacheCompositionPercent: number;
  cachePromptCompositionSegments: SessionCacheCompositionSegment[];
  cachePromptCompositionTotalTokens: number;
  cachePromptDonutSegments: CacheDonutSegment[];
  cacheCompositionPercent: number;
  averageCacheObservedTurnCount: number;
  averageCacheCompositionPercent: number;
  cacheCompositionAverageValue: string;
  cacheDetailAvailable: boolean;
  cacheDetailDialogTitle: string;
  cacheDetailOpenLabel: string;
  cacheCompositionSummary: string;
  cacheCompositionTitle: string;
  cacheCompositionUpperBoundLabel: string;
  cacheCompositionAverageLabel: string;
};

export function buildChatCacheDetailViewModel(options: {
  detail: SessionDetail | null | undefined;
  lastCacheComposition: SessionCacheCompositionDiagnostics | null | undefined;
  lastCacheDiagnostics: SessionCacheCompositionDiagnostics | null | undefined;
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  numberFormatter: Intl.NumberFormat;
}): ChatCacheDetailViewModel {
  const {
    detail,
    lastCacheComposition,
    lastCacheDiagnostics,
    lang,
    t,
    numberFormatter,
  } = options;

  const providerCacheInputTokens = Math.max(0, lastCacheComposition?.calibratedInputTokens ?? lastCacheComposition?.inputTokens ?? 0);
  const providerCachedInputTokens = Math.max(
    0,
    Math.min(
      lastCacheComposition?.calibratedCachedInputTokens ?? lastCacheComposition?.cachedInputTokens ?? 0,
      providerCacheInputTokens,
    ),
  );
  const providerUncachedInputTokens = Math.max(
    0,
    lastCacheComposition?.uncachedInputTokens ?? (providerCacheInputTokens - providerCachedInputTokens),
  );
  const cacheCalibrationStatus = lastCacheComposition?.calibrationStatus || "";
  const cacheCalibrationReason = lastCacheComposition?.calibrationReason || "";
  const cacheComputedOverestimatedInputTokens = Math.max(0, lastCacheComposition?.computedOverestimatedInputTokens ?? 0);
  const cacheProviderExtraCachedInputTokens = Math.max(0, lastCacheComposition?.providerExtraCachedInputTokens ?? 0);
  const cacheCalibrationSummaryText = cacheCalibrationSummaryLabel(
    cacheCalibrationStatus,
    cacheCalibrationReason,
    cacheComputedOverestimatedInputTokens,
    cacheProviderExtraCachedInputTokens,
    numberFormatter,
    lang,
  );

  const trueCacheDonutSegments = buildCacheDonutSegments(
    [
      {
        key: "cached",
        label: t("cacheSegment_cached"),
        tokens: providerCachedInputTokens,
        status: "hit",
        source: "provider_usage",
        description: lang === "zh" ? "上游返回的真实缓存命中输入 token。" : "Provider-reported cached input tokens.",
      },
      {
        key: "uncached",
        label: t("cacheSegment_uncached"),
        tokens: Math.max(0, providerCacheInputTokens - providerCachedInputTokens),
        status: "miss",
        source: "provider_usage",
        description: lang === "zh" ? "上游返回的非缓存命中输入 token。" : "Provider-reported input tokens that were not cache hits.",
      },
    ],
    providerCacheInputTokens,
  );

  const computedCacheCompositionSegments = (lastCacheComposition?.computedSegments ?? [])
    .filter((segment: SessionCacheCompositionSegment) => (segment.tokens ?? 0) > 0 || segment.key === "computed_missing")
    .map((segment) => ({
      ...segment,
      label: promptSegmentDisplayLabel(segment, lang, t),
    }));
  const computedCacheCompositionTotalTokens = Math.max(
    lastCacheComposition?.computedInputTokens ?? 0,
    computedCacheCompositionSegments.reduce((total, segment) => total + Math.max(0, segment.tokens ?? 0), 0),
  );
  const upperBoundCacheInputTokens = Math.max(
    lastCacheDiagnostics?.upperBoundInputTokens ?? 0,
    computedCacheCompositionTotalTokens,
  );
  const upperBoundCachedInputTokens = Math.max(
    0,
    Math.min(
      lastCacheDiagnostics?.upperBoundCachedInputTokens ?? lastCacheDiagnostics?.computedCachedInputTokens ?? 0,
      upperBoundCacheInputTokens,
    ),
  );
  const upperBoundCacheHitRate = upperBoundCacheInputTokens > 0
    ? (lastCacheDiagnostics?.upperBoundCacheHitRate ?? (upperBoundCachedInputTokens / upperBoundCacheInputTokens))
    : 0;

  const cachePromptCompositionSegments = (
    lastCacheComposition?.calibratedSegments?.length
      ? (lastCacheComposition.calibratedSegments ?? [])
      : computedCacheCompositionSegments
  )
    .filter((segment: SessionCacheCompositionSegment) => (segment.tokens ?? 0) > 0 || segment.key === "computed_missing")
    .map((segment) => ({
      ...segment,
      label: promptSegmentDisplayLabel(segment, lang, t),
    }));
  const cachePromptCompositionTotalTokens = Math.max(
    computedCacheCompositionTotalTokens,
    cachePromptCompositionSegments.reduce((total, segment) => total + Math.max(0, segment.tokens ?? 0), 0),
  );
  const cachePromptDonutSegments = buildCacheDonutSegments(cachePromptCompositionSegments, cachePromptCompositionTotalTokens);
  const cacheCompositionPercent = Math.round(Math.max(0, Math.min(1, lastCacheComposition?.cacheHitRate ?? 0)) * 100);
  const upperBoundCacheCompositionPercent = Math.round(Math.max(0, Math.min(1, upperBoundCacheHitRate)) * 100);
  const averageCacheObservedTurnCount = Math.max(
    0,
    lastCacheComposition?.averageObservedTurnCount || detail?.cacheUsage?.totalObservedTurnCount || 0,
  );
  const averageCacheInputTokens = Math.max(
    0,
    lastCacheComposition?.averageInputTokens || detail?.cacheUsage?.totalInputTokens || 0,
  );
  const averageCachedInputTokens = Math.max(
    0,
    lastCacheComposition?.averageCachedInputTokens || detail?.cacheUsage?.totalCachedInputTokens || 0,
  );
  const averageCacheHitRate = averageCacheInputTokens > 0
    ? averageCachedInputTokens / averageCacheInputTokens
    : (detail?.cacheUsage?.totalCacheHitRate ?? lastCacheComposition?.averageCacheHitRate ?? 0);
  const averageCacheCompositionPercent = Math.round(Math.max(0, Math.min(1, averageCacheHitRate)) * 100);
  const cacheCompositionTrueLabel = lang === "zh" ? "真" : "true";
  const cacheCompositionUpperBoundLabel = lang === "zh" ? "计" : "calc";
  const cacheCompositionAverageLabel = lang === "zh" ? "均" : "avg";
  const cacheCompositionAverageValue = averageCacheObservedTurnCount > 0 ? `${averageCacheCompositionPercent}%` : "--";
  const cacheDetailAvailable = Boolean(lastCacheComposition);
  const cacheDetailDialogTitle = lang === "zh" ? "缓存命中详情" : "Cache hit details";
  const cacheDetailOpenLabel = lang === "zh" ? "查看上一轮缓存命中详情" : "View previous cache hit details";
  // Rail summary: lead with last-turn provider truth; park session average second
  // so early low-hit tool loops don't read as "cache is broken".
  const cacheCompositionSummary = lastCacheComposition
    ? lastCacheComposition.source === "provider_usage"
      ? averageCacheObservedTurnCount > 1
        ? (lang === "zh"
          ? `上轮 ${cacheCompositionPercent}% · 会话均 ${cacheCompositionAverageValue}`
          : `Last ${cacheCompositionPercent}% · avg ${cacheCompositionAverageValue}`)
        : `${cacheCompositionPercent}%`
      : lastCacheComposition.source === "not_called"
        ? t("cacheHitNotCalled")
        : t("cacheHitMissing")
    : t("cacheObservationPending");
  const cacheCompositionTitle = lastCacheComposition
    ? lastCacheComposition.source === "provider_usage"
      ? [
        lang === "zh"
          ? `上轮真实命中 ${cacheCompositionPercent}%（${numberFormatter.format(providerCachedInputTokens)} / ${numberFormatter.format(providerCacheInputTokens)}）`
          : `Last-turn true hit ${cacheCompositionPercent}% (${numberFormatter.format(providerCachedInputTokens)} / ${numberFormatter.format(providerCacheInputTokens)})`,
        averageCacheObservedTurnCount > 1
          ? (lang === "zh"
            ? `会话平均 ${cacheCompositionAverageValue} · ${numberFormatter.format(averageCacheObservedTurnCount)} 轮（含工具风暴早期低命中）`
            : `Session avg ${cacheCompositionAverageValue} · ${numberFormatter.format(averageCacheObservedTurnCount)} turns (early tool-loop turns pull this down)`)
          : "",
        cacheComputedOverestimatedInputTokens > 0
          ? (lang === "zh"
            ? `前缀上界未完全兑现 ${numberFormatter.format(cacheComputedOverestimatedInputTokens)} tokens`
            : `Stable-prefix upper bound not fully realized: ${numberFormatter.format(cacheComputedOverestimatedInputTokens)} tokens`)
          : "",
      ].filter(Boolean).join(" · ")
      : lastCacheComposition.source === "not_called"
        ? t("cacheHitNotCalled")
        : t("cacheHitMissing")
    : t("cacheObservationPending");

  return {
    providerCacheInputTokens,
    providerCachedInputTokens,
    providerUncachedInputTokens,
    cacheCalibrationStatus,
    cacheCalibrationReason,
    cacheComputedOverestimatedInputTokens,
    cacheProviderExtraCachedInputTokens,
    cacheCalibrationSummaryText,
    trueCacheDonutSegments,
    computedCacheCompositionSegments,
    computedCacheCompositionTotalTokens,
    upperBoundCacheInputTokens,
    upperBoundCachedInputTokens,
    upperBoundCacheCompositionPercent,
    cachePromptCompositionSegments,
    cachePromptCompositionTotalTokens,
    cachePromptDonutSegments,
    cacheCompositionPercent,
    averageCacheObservedTurnCount,
    averageCacheCompositionPercent,
    cacheCompositionAverageValue,
    cacheDetailAvailable,
    cacheDetailDialogTitle,
    cacheDetailOpenLabel,
    cacheCompositionSummary,
    cacheCompositionTitle,
    cacheCompositionUpperBoundLabel,
    cacheCompositionAverageLabel,
  };
}
