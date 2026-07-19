import type { RuntimeSummary, SessionDetail } from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionary";
import { clampPercent, contextUsagePercent, formatRelativeTime } from "../chatShellFormat";
import type { TokenSpeedTrackerState } from "../chatTokenSpeed";
import { formatTokenSpeedValue, isBusyPhase } from "./chatCodingRouteViewModel";
import type { TokenCoreStatusMetric } from "./TokenCoreStatusPanel";

export type ChatTokenStatusCompression = RuntimeSummary["contextCompression"] | null | undefined;

export type ChatTokenStatusCacheInputs = {
  cacheDetailAvailable: boolean;
  cacheCompositionPercent: number;
  providerCachedInputTokens: number;
  providerCacheInputTokens: number;
  cacheCompositionSummary: string;
  cacheDetailOpenLabel: string;
  cacheCompositionTitle: string;
};

export type ChatTokenStatusViewModel = {
  tokenStatusMetrics: TokenCoreStatusMetric[];
  modelInputTokens: number;
  modelInputAvailable: boolean;
  modelInputMetaLine: string;
  modelInputTitle: string;
  llmUsageLine: string;
  llmUsageTitle: string;
  compressionThresholdValue: string;
  compressionThresholdMeta: string;
  tokenCompressionStrategyTitle: string;
  tokenStatusCacheTitle: string;
  tokenStatusCompressionTitle: string;
};

/**
 * Pure builder for TokenCoreStatusPanel metrics and related hover copy.
 * Does not own stream/query state.
 */
export function buildChatTokenStatusViewModel(options: {
  detail: SessionDetail | null | undefined;
  lastCacheComposition: SessionDetail["lastCacheComposition"] | null | undefined;
  lastContextComposition: SessionDetail["lastContextComposition"] | null | undefined;
  compression: ChatTokenStatusCompression;
  cache: ChatTokenStatusCacheInputs;
  tokenSpeedTracker: TokenSpeedTrackerState | null | undefined;
  activeSessionId: string | null | undefined;
  groupPanelActive: boolean;
  sessionStateValue: string;
  sessionStateLabel: string;
  sessionStateLine: string;
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  numberFormatter: Intl.NumberFormat;
  compactNumberFormatter: Intl.NumberFormat;
  locale: string;
  formatTime: (value: string) => string;
  nowMs?: number;
}): ChatTokenStatusViewModel {
  const {
    detail,
    lastCacheComposition,
    lastContextComposition,
    compression,
    cache,
    tokenSpeedTracker,
    activeSessionId,
    groupPanelActive,
    sessionStateValue,
    sessionStateLabel,
    sessionStateLine,
    lang,
    t,
    numberFormatter,
    compactNumberFormatter,
    locale,
    formatTime,
    nowMs = Date.now(),
  } = options;

  const sessionCacheUsage = detail?.cacheUsage;
  const sessionContextUsage = detail?.contextUsage;
  const sessionLlmUsage = detail?.llmUsage ?? null;
  const hasProviderLlmUsage = sessionLlmUsage?.source === "provider_usage";
  const hasProviderCacheUsage = sessionCacheUsage?.source === "provider_usage";
  const llmUsageNotCalled = sessionLlmUsage?.source === "not_called" || sessionCacheUsage?.source === "not_called";
  const cacheHitRatePercent = Math.round(Math.max(0, Math.min(1, sessionCacheUsage?.turnCacheHitRate ?? 0)) * 100);
  const cacheHitLine = hasProviderCacheUsage && sessionCacheUsage
    ? `${numberFormatter.format(sessionCacheUsage.turnCachedInputTokens)} / ${numberFormatter.format(sessionCacheUsage.turnInputTokens)} · ${cacheHitRatePercent}%`
    : llmUsageNotCalled
      ? t("cacheHitNotCalled")
      : t("cacheHitMissing");
  const llmUsageLine = hasProviderLlmUsage
    ? lang === "zh"
      ? `${numberFormatter.format(sessionLlmUsage.inputTokens)} · 缓 ${numberFormatter.format(sessionLlmUsage.cachedInputTokens)}`
      : `${numberFormatter.format(sessionLlmUsage.inputTokens)} in · ${numberFormatter.format(sessionLlmUsage.cachedInputTokens)} cached`
    : llmUsageNotCalled
      ? t("llmUsageNotCalled")
      : t("llmUsageMissing");
  const llmUsageTitle = hasProviderLlmUsage
    ? [
      `${numberFormatter.format(sessionLlmUsage.inputTokens)} in`,
      `${numberFormatter.format(sessionLlmUsage.outputTokens)} out`,
      `${numberFormatter.format(sessionLlmUsage.cachedInputTokens)} cached`,
      `${numberFormatter.format(sessionLlmUsage.cacheCreationInputTokens ?? 0)} write`,
      `${numberFormatter.format(sessionLlmUsage.uncachedInputTokens ?? 0)} uncached`,
    ].join(" · ")
    : llmUsageNotCalled
      ? t("llmUsageNotCalled")
      : t("llmUsageMissing");

  const panelContextUsed = lastContextComposition?.totalTokens ?? sessionContextUsage?.used ?? 0;
  const panelContextLimit = lastContextComposition?.limitTokens ?? sessionContextUsage?.limit ?? 0;
  const contextPercent = contextUsagePercent(panelContextUsed, panelContextLimit);
  const compressionCurrentPercent = compression
    ? Math.round(Math.max(0, Math.min(1, compression.usageRatio || 0)) * 100)
    : contextPercent;
  const compressionLevelLabel = compression?.enabled === false
    ? t("compressionDisabled")
    : compression?.currentLevel
      ? compression.currentLevel === "normal"
        ? (lang === "zh" ? "未到阈值" : "below threshold")
        : (lang === "zh" ? `${compression.currentLevel} 档` : `${compression.currentLevel} level`)
      : "--";
  const compressionMainLine = compression
    ? `${numberFormatter.format(compression.currentTokens)} / ${numberFormatter.format(compression.effectiveTokenLimit)} · ${compressionCurrentPercent}%`
    : t("loadingContext");
  const compressionPolicySourceLine = compression
    ? compression.policySource === "agent_custom"
      ? (lang === "zh" ? "Agent 自定义策略" : "Agent custom policy")
      : (lang === "zh" ? "继承全局策略" : "Inherited global policy")
    : t("loadingContext");
  const compressionScopeLine = compression
    ? `${t("compressionScopeRuntime")} · ${compressionPolicySourceLine}`
    : t("loadingContext");
  const compressionModelWindowLine = compression
    ? numberFormatter.format(compression.contextWindowLimit)
    : "--";
  const compressionTitleLine = compression
    ? `${compressionMainLine} · ${compressionScopeLine} · ${t("compressionLimitBasisEffective")} · window ${numberFormatter.format(compression.contextWindowLimit)} · source ${compression.source || "runtime_state"}`
    : t("loadingContext");

  const modelInputAvailable =
    lastCacheComposition?.calibratedInputTokens != null
    || (hasProviderLlmUsage && sessionLlmUsage.inputTokens != null)
    || lastCacheComposition?.inputTokens != null
    || (hasProviderCacheUsage && sessionCacheUsage?.turnInputTokens != null);
  const modelInputTokens = Math.max(
    0,
    lastCacheComposition?.calibratedInputTokens
      ?? (hasProviderLlmUsage ? sessionLlmUsage.inputTokens : undefined)
      ?? lastCacheComposition?.inputTokens
      ?? (hasProviderCacheUsage ? sessionCacheUsage?.turnInputTokens : undefined)
      ?? 0,
  );
  const modelCachedInputTokens = Math.max(
    0,
    Math.min(
      lastCacheComposition?.calibratedCachedInputTokens
        ?? (hasProviderLlmUsage ? sessionLlmUsage.cachedInputTokens : undefined)
        ?? lastCacheComposition?.cachedInputTokens
        ?? (hasProviderCacheUsage ? sessionCacheUsage?.turnCachedInputTokens : undefined)
        ?? 0,
      modelInputTokens,
    ),
  );
  const modelInputLimitTokens = Math.max(
    0,
    lastContextComposition?.limitTokens
      ?? sessionContextUsage?.limit
      ?? compression?.contextWindowLimit
      ?? 0,
  );
  const modelInputPercent = modelInputLimitTokens > 0
    ? Math.round(Math.min(1, modelInputTokens / modelInputLimitTokens) * 100)
    : 0;
  const modelInputSourceLine = modelInputAvailable
    ? lastCacheComposition?.calibratedInputTokens != null
      ? (lang === "zh" ? "厂商校准输入" : "provider-calibrated input")
      : hasProviderLlmUsage
        ? (lang === "zh" ? "厂商 usage 输入" : "provider usage input")
        : lastCacheComposition?.inputTokens != null
          ? (lang === "zh" ? "缓存观测输入" : "cache-observed input")
          : (lang === "zh" ? "厂商 cache usage 输入" : "provider cache usage input")
    : llmUsageNotCalled
      ? t("llmUsageNotCalled")
      : t("llmUsageMissing");
  const modelInputMetaLine = modelInputAvailable
    ? modelInputLimitTokens > 0
      ? `${numberFormatter.format(modelInputTokens)} / ${numberFormatter.format(modelInputLimitTokens)} · ${modelInputPercent}%`
      : `${numberFormatter.format(modelInputTokens)} tokens`
    : modelInputSourceLine;
  const modelInputTitle = [
    lang === "zh"
      ? `模型输入 ${numberFormatter.format(modelInputTokens)}`
      : `Model input ${numberFormatter.format(modelInputTokens)}`,
    modelInputLimitTokens > 0 ? `${lang === "zh" ? "窗口" : "window"} ${numberFormatter.format(modelInputLimitTokens)} · ${modelInputPercent}%` : "",
    `${lang === "zh" ? "缓存输入" : "cached input"} ${numberFormatter.format(modelCachedInputTokens)}`,
    modelInputSourceLine,
    llmUsageTitle,
  ].filter(Boolean).join("\n");

  const lastCompression = compression?.lastCompression ?? null;
  const lastCompressionSourceText = (() => {
    if (!lastCompression) {
      return "";
    }
    switch (lastCompression.triggerSource) {
      case "manual":
        return lang === "zh" ? "Agent 主动请求" : "Agent requested";
      case "provider_limit":
        return lang === "zh" ? "上下文上限触发" : "Context limit triggered";
      case "auto":
        return lang === "zh" ? "阈值自动触发" : "Threshold triggered";
      default:
        return String(lastCompression.triggerSource || "").trim() || (lang === "zh" ? "未知来源" : "Unknown source");
    }
  })();
  const lastCompressionLine = lastCompression
    ? (lang === "zh"
      ? `${lastCompressionSourceText}，${lastCompression.level || "--"} 档：${numberFormatter.format(lastCompression.beforeTokens)} -> ${numberFormatter.format(lastCompression.afterTokens)}，节省 ${numberFormatter.format(lastCompression.savedTokens)} token`
      : `${lastCompressionSourceText}, ${lastCompression.level || "--"} level: ${numberFormatter.format(lastCompression.beforeTokens)} -> ${numberFormatter.format(lastCompression.afterTokens)}, saved ${numberFormatter.format(lastCompression.savedTokens)} tokens`)
    : t("compressionNoRecord");
  const compressionUpdatedLine = lastCompression?.timestamp
    ? formatRelativeTime(lastCompression.timestamp, nowMs, locale) || formatTime(lastCompression.timestamp)
    : compression?.updatedAt
      ? formatRelativeTime(compression.updatedAt, nowMs, locale) || formatTime(compression.updatedAt)
      : "";

  const tokenCompressionStrategyLevels = compression?.strategy?.levels ?? [];
  const tokenCompressionStrategyKeywords = (compression?.strategy?.errorProtectionKeywords ?? []).join(" / ") || "--";
  const tokenCompressionLevelLabel = compressionLevelLabel === "--"
    ? (lang === "zh" ? "默认" : "Default")
    : compressionLevelLabel;
  const tokenCompressionStrategyTitle = tokenCompressionStrategyLevels.length
    ? tokenCompressionStrategyLevels
      .map((level) => `${level.level}: ${Math.round(level.thresholdRatio * 100)}% / ${numberFormatter.format(level.thresholdTokens)}`)
      .join(" · ")
    : tokenCompressionStrategyKeywords;
  const compressionThresholdValue = compression
    ? `${numberFormatter.format(compression.currentTokens)} / ${numberFormatter.format(compression.effectiveTokenLimit)}`
    : t("loadingContext");
  const compressionThresholdMeta = compression
    ? (lang === "zh"
      ? `压缩阈值 ${compressionCurrentPercent}% · ${compressionLevelLabel}`
      : `threshold ${compressionCurrentPercent}% · ${compressionLevelLabel}`)
    : "";
  const tokenStatusCacheTitle = [
    cache.cacheDetailOpenLabel,
    cache.cacheCompositionTitle,
    cacheHitLine,
    llmUsageLine,
    llmUsageTitle,
  ].filter(Boolean).join("\n");
  const tokenStatusCompressionTitle = [
    compressionTitleLine,
    compressionThresholdValue,
    compressionThresholdMeta,
    compressionModelWindowLine !== "--" ? `${lang === "zh" ? "模型窗口" : "model window"} ${compressionModelWindowLine}` : "",
    tokenCompressionStrategyTitle !== "--" ? tokenCompressionStrategyTitle : "",
    lastCompressionLine,
    compressionUpdatedLine ? `${lang === "zh" ? "更新" : "updated"} ${compressionUpdatedLine}` : "",
  ].filter(Boolean).join("\n");

  const conversationChainTokenSpeedActive = Boolean(activeSessionId)
    && !groupPanelActive
    && isBusyPhase(sessionStateValue);
  const tokenSpeedRateValue = formatTokenSpeedValue(tokenSpeedTracker?.tokensPerSecond);
  const tokenSpeedValue = tokenSpeedRateValue
    || (conversationChainTokenSpeedActive ? t("tokenSpeedSampling") : "--");
  const tokenSpeedMeta = tokenSpeedRateValue
    ? t("tokenSpeedEstimated")
    : conversationChainTokenSpeedActive
      ? sessionStateLabel
      : t("tokenSpeedEstimated");
  const tokenSpeedTitle = [
    t("tokenSpeedEstimated"),
    sessionStateLabel,
    sessionStateLine,
    tokenSpeedTracker
      ? `${lang === "zh" ? "已估算输出" : "estimated output"} ${numberFormatter.format(tokenSpeedTracker.tokenCount)} tokens`
      : "",
  ].filter(Boolean).join("\n");
  const tokenSpeedPercent = clampPercent(
    tokenSpeedTracker?.tokensPerSecond
      ? Math.min(100, Math.round(tokenSpeedTracker.tokensPerSecond))
      : conversationChainTokenSpeedActive
        ? 8
        : 0,
  );

  const tokenStatusMetrics: TokenCoreStatusMetric[] = [
    {
      key: "cache",
      label: t("previousCacheHit"),
      value: cache.cacheDetailAvailable ? `${cache.cacheCompositionPercent}%` : "--",
      meta: cache.cacheDetailAvailable
        ? `${numberFormatter.format(cache.providerCachedInputTokens)} / ${numberFormatter.format(cache.providerCacheInputTokens)}`
        : cache.cacheCompositionSummary,
      title: tokenStatusCacheTitle,
      percent: clampPercent(cache.cacheDetailAvailable ? cache.cacheCompositionPercent : 0),
      tone: "cache",
    },
    {
      key: "modelInput",
      label: lang === "zh" ? "模型输入" : "Model input",
      value: modelInputAvailable ? numberFormatter.format(modelInputTokens) : "--",
      displayValue: modelInputAvailable ? compactNumberFormatter.format(modelInputTokens) : "--",
      meta: modelInputMetaLine,
      title: modelInputTitle,
      percent: clampPercent(modelInputPercent),
      tone: "modelInput",
    },
    {
      key: "compression",
      label: lang === "zh" ? "压缩状态" : "Compression",
      value: compression ? `${compressionCurrentPercent}%` : "--",
      meta: compression ? tokenCompressionLevelLabel : t("loadingContext"),
      title: tokenStatusCompressionTitle,
      percent: clampPercent(compression ? compressionCurrentPercent : 0),
      tone: "compression",
    },
    {
      key: "speed",
      label: t("tokenSpeed"),
      value: tokenSpeedValue,
      meta: tokenSpeedMeta,
      title: tokenSpeedTitle,
      percent: tokenSpeedPercent,
      tone: "speed",
    },
  ];

  return {
    tokenStatusMetrics,
    modelInputTokens,
    modelInputAvailable,
    modelInputMetaLine,
    modelInputTitle,
    llmUsageLine,
    llmUsageTitle,
    compressionThresholdValue,
    compressionThresholdMeta,
    tokenCompressionStrategyTitle,
    tokenStatusCacheTitle,
    tokenStatusCompressionTitle,
  };
}
