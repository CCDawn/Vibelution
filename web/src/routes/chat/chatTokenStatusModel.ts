import type { RuntimeSummary, SessionDetail } from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionary";
import { clampPercent, contextUsagePercent } from "../chatShellFormat";
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
 * Keep ring-facing compact numbers single-line inside the 28px status ring.
 * zh-CN compact often yields "2.3万", which wraps to two lines and misaligns the four cards.
 */
export function formatTokenStatusRingCompact(
  value: number,
  compactNumberFormatter: Intl.NumberFormat,
): string {
  const local = compactNumberFormatter
    .format(value)
    .replace(/\u00a0/g, "")
    .replace(/\s/g, "");
  const graphemes = Array.from(local);
  const hasCjk = /[\u3400-\u9fff]/.test(local);
  // CJK units are roughly full-width; more than 3 graphemes will not fit one line.
  if ((hasCjk && graphemes.length > 3) || graphemes.length > 4) {
    return new Intl.NumberFormat("en", {
      notation: "compact",
      maximumFractionDigits: 1,
    })
      .format(value)
      .replace(/\u00a0/g, "")
      .replace(/\s/g, "");
  }
  return local;
}

/**
 * Pure builder for TokenCoreStatusPanel metrics and related hover copy.
 * Does not own stream/query state.
 */
export function buildChatTokenStatusViewModel(options: {
  detail: SessionDetail | null | undefined;
  lastCacheComposition: SessionDetail["lastCacheComposition"] | null | undefined;
  lastContextComposition: SessionDetail["lastContextComposition"] | null | undefined;
  compression: ChatTokenStatusCompression;
  /** When false, compression is intentionally unavailable (not still loading). */
  runtimeMatchesSelectedSession?: boolean;
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
    runtimeMatchesSelectedSession = true,
    cache,
    tokenSpeedTracker,
    activeSessionId,
    groupPanelActive,
    sessionStateValue,
    sessionStateLabel,
    sessionStateLine: _sessionStateLine,
    lang,
    t,
    numberFormatter,
    compactNumberFormatter,
    locale: _locale,
    formatTime: _formatTime,
    nowMs: _nowMs,
  } = options;
  const compressionUnavailableForSession = !compression && !runtimeMatchesSelectedSession;
  const compressionUnavailableLine = compressionUnavailableForSession
    ? t("compressionScopeInactiveSession")
    : t("loadingContext");
  const compressionUnavailableTitle = compressionUnavailableForSession
    ? t("compressionScopeInactiveSessionHint")
    : t("loadingContext");

  const sessionCacheUsage = detail?.cacheUsage;
  const sessionContextUsage = detail?.contextUsage;
  const sessionLlmUsage = detail?.llmUsage ?? null;
  const hasProviderLlmUsage = sessionLlmUsage?.source === "provider_usage";
  const hasProviderLlmCacheUsage = hasProviderLlmUsage && Boolean(
    sessionLlmUsage?.cacheUsageObserved
    ?? ((sessionLlmUsage?.cachedInputTokens ?? 0) > 0
      || (sessionLlmUsage?.cacheCreationInputTokens ?? 0) > 0),
  );
  const hasProviderCacheUsage = sessionCacheUsage?.source === "provider_usage" && Boolean(
    sessionCacheUsage.cacheUsageObserved
    ?? ((sessionCacheUsage.turnCachedInputTokens ?? 0) > 0),
  );
  const hasObservedLastCacheComposition = lastCacheComposition?.source === "provider_usage" && Boolean(
    lastCacheComposition.cacheUsageObserved
    ?? ((lastCacheComposition.cachedInputTokens ?? 0) > 0
      || (lastCacheComposition.cacheCreationInputTokens ?? 0) > 0),
  );
  const llmUsageNotCalled = sessionLlmUsage?.source === "not_called" || sessionCacheUsage?.source === "not_called";
  const cacheHitRatePercent = Math.round(Math.max(0, Math.min(1, sessionCacheUsage?.turnCacheHitRate ?? 0)) * 100);
  const cacheHitLine = hasProviderCacheUsage && sessionCacheUsage
    ? `${numberFormatter.format(sessionCacheUsage.turnCachedInputTokens)} / ${numberFormatter.format(sessionCacheUsage.turnInputTokens)} · ${cacheHitRatePercent}%`
    : llmUsageNotCalled
      ? t("cacheHitNotCalled")
      : t("cacheHitMissing");
  const llmUsageLine = hasProviderLlmUsage
    ? lang === "zh"
      ? hasProviderLlmCacheUsage
        ? `${numberFormatter.format(sessionLlmUsage.inputTokens)} · 缓 ${numberFormatter.format(sessionLlmUsage.cachedInputTokens)}`
        : `${numberFormatter.format(sessionLlmUsage.inputTokens)} · ${t("cacheHitMissing")}`
      : hasProviderLlmCacheUsage
        ? `${numberFormatter.format(sessionLlmUsage.inputTokens)} in · ${numberFormatter.format(sessionLlmUsage.cachedInputTokens)} cached`
        : `${numberFormatter.format(sessionLlmUsage.inputTokens)} in · ${t("cacheHitMissing")}`
    : llmUsageNotCalled
      ? t("llmUsageNotCalled")
      : t("llmUsageMissing");
  const llmUsageTitle = hasProviderLlmUsage
    ? hasProviderLlmCacheUsage
      ? [
        `${numberFormatter.format(sessionLlmUsage.inputTokens)} in`,
        `${numberFormatter.format(sessionLlmUsage.outputTokens)} out`,
        `${numberFormatter.format(sessionLlmUsage.cachedInputTokens)} cached`,
        `${numberFormatter.format(sessionLlmUsage.cacheCreationInputTokens ?? 0)} write`,
        `${numberFormatter.format(sessionLlmUsage.uncachedInputTokens ?? 0)} uncached`,
      ].join(" · ")
      : [
        `${numberFormatter.format(sessionLlmUsage.inputTokens)} in`,
        `${numberFormatter.format(sessionLlmUsage.outputTokens)} out`,
        t("cacheHitMissing"),
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
    : compressionUnavailableLine;
  const compressionPolicyUnmaterialized = compression?.policyMode === "unmaterialized"
    || compression?.policySource === "migration_required";
  const compressionPolicySourceLine = compression
    ? compressionPolicyUnmaterialized
      ? (lang === "zh" ? "Agent 策略未物化" : "Agent policy not materialized")
      : compression.policySource === "agent_custom"
        ? (lang === "zh" ? "Agent 自定义策略" : "Agent custom policy")
        : (lang === "zh" ? "继承全局策略" : "Inherited global policy")
    : compressionUnavailableLine;

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
      (hasObservedLastCacheComposition ? lastCacheComposition?.calibratedCachedInputTokens : undefined)
        ?? (hasProviderLlmCacheUsage ? sessionLlmUsage.cachedInputTokens : undefined)
        ?? (hasObservedLastCacheComposition ? lastCacheComposition?.cachedInputTokens : undefined)
        ?? (hasProviderCacheUsage ? sessionCacheUsage?.turnCachedInputTokens : undefined)
        ?? 0,
      modelInputTokens,
    ),
  );
  // Max context window: only trust explicit composition/session limits. Never invent 32k/128k.
  const modelInputLimitTokens = Math.max(
    0,
    lastContextComposition?.limitTokens
      ?? sessionContextUsage?.limit
      ?? 0,
  );
  const modelInputLimitSource = String(
    lastContextComposition?.limitSource
      ?? sessionContextUsage?.limitSource
      ?? "",
  ).trim();
  const modelInputLimitMissing = modelInputLimitTokens <= 0
    || modelInputLimitSource === "missing"
    || modelInputLimitSource === "static_fallback"
    || modelInputLimitSource === "context_compression_fallback";
  const modelInputPercent = !modelInputLimitMissing && modelInputLimitTokens > 0
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
  const sessionLimitError = String(sessionContextUsage?.limitError || "").trim();
  const modelInputLimitError = modelInputLimitMissing
    ? (sessionLimitError
      || (lang === "zh"
        ? "未找到模型 max 上下文窗口（禁止默认兜底）。请在设置中为对话模型配置 context_window，或运行模型发现写入后再试。"
        : "Model max context window is missing (silent defaults are disabled). Set context_window for the dialogue model in settings, or run model discovery."))
    : "";
  const modelInputMetaLine = modelInputLimitMissing
    ? modelInputLimitError
    : modelInputAvailable
      ? `${numberFormatter.format(modelInputTokens)} / ${numberFormatter.format(modelInputLimitTokens)} · ${modelInputPercent}%`
      : modelInputSourceLine;
  /** Hover: only actionable high-value rows (≤3). Detail dialogs hold the rest. */
  const modelInputTitleLines = modelInputLimitMissing
    ? [modelInputLimitError]
    : modelInputAvailable
      ? [
          `${numberFormatter.format(modelInputTokens)} / ${numberFormatter.format(modelInputLimitTokens)} · ${modelInputPercent}%`,
          modelCachedInputTokens > 0
            ? (lang === "zh"
              ? `缓存命中 ${numberFormatter.format(modelCachedInputTokens)}`
              : `Cached ${numberFormatter.format(modelCachedInputTokens)}`)
            : "",
        ].filter(Boolean)
      : [modelInputSourceLine];
  const modelInputTitle = modelInputTitleLines.join("\n");

  const lastCompression = compression?.lastCompression ?? null;
  const lastCompressionSourceText = (() => {
    if (!lastCompression) {
      return "";
    }
    switch (lastCompression.triggerSource) {
      case "manual":
        return lang === "zh" ? "主动压缩" : "Manual";
      case "provider_limit":
        return lang === "zh" ? "上限触发" : "Limit";
      case "auto":
        return lang === "zh" ? "阈值触发" : "Threshold";
      default:
        return String(lastCompression.triggerSource || "").trim() || (lang === "zh" ? "压缩" : "Compress");
    }
  })();
  const lastCompressionLine = lastCompression
    ? (lang === "zh"
      ? `${lastCompressionSourceText} ${lastCompression.level || ""}：${numberFormatter.format(lastCompression.beforeTokens)}→${numberFormatter.format(lastCompression.afterTokens)}（−${numberFormatter.format(lastCompression.savedTokens)}）`
      : `${lastCompressionSourceText} ${lastCompression.level || ""}: ${numberFormatter.format(lastCompression.beforeTokens)}→${numberFormatter.format(lastCompression.afterTokens)} (−${numberFormatter.format(lastCompression.savedTokens)})`)
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
    : compressionUnavailableLine;
  const compressionThresholdMeta = compression
    ? (lang === "zh"
      ? `压缩阈值 ${compressionCurrentPercent}% · ${compressionLevelLabel}`
      : `threshold ${compressionCurrentPercent}% · ${compressionLevelLabel}`)
    : "";
  // Cache hover: hit + ratio only (full breakdown lives in cache detail dialog).
  const tokenStatusCacheTitleLines = cache.cacheDetailAvailable
    ? [
        `${cache.cacheCompositionPercent}% · ${numberFormatter.format(cache.providerCachedInputTokens)} / ${numberFormatter.format(cache.providerCacheInputTokens)}`,
        lang === "zh" ? "点击查看明细" : "Click for detail",
      ]
    : [cacheHitLine || cache.cacheCompositionSummary || t("cacheHitMissing")].filter(Boolean);
  const tokenStatusCacheTitle = tokenStatusCacheTitleLines.join("\n");
  // Compression hover: usage + policy/level + last event only (no strategy dump / source noise).
  const tokenStatusCompressionTitleLines = compression
    ? [
        compressionMainLine,
        [compression?.enabled === false ? t("compressionDisabled") : tokenCompressionLevelLabel, compressionPolicySourceLine]
          .filter(Boolean)
          .join(" · "),
        lastCompressionLine,
      ].filter(Boolean)
    : [compressionUnavailableTitle];
  const tokenStatusCompressionTitle = tokenStatusCompressionTitleLines.join("\n");

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
  const tokenSpeedTitleLines = [
    tokenSpeedRateValue
      ? (lang === "zh" ? `${tokenSpeedRateValue} tok/s` : `${tokenSpeedRateValue} tok/s`)
      : conversationChainTokenSpeedActive
        ? t("tokenSpeedSampling")
        : (lang === "zh" ? "暂无速度" : "No speed yet"),
    conversationChainTokenSpeedActive && !tokenSpeedRateValue ? sessionStateLabel : "",
  ].filter(Boolean);
  const tokenSpeedTitle = tokenSpeedTitleLines.join("\n");
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
      titleLines: tokenStatusCacheTitleLines,
      percent: clampPercent(cache.cacheDetailAvailable ? cache.cacheCompositionPercent : 0),
      tone: "cache",
    },
    {
      key: "modelInput",
      label: lang === "zh" ? "模型输入" : "Model input",
      value: modelInputLimitMissing
        ? (lang === "zh" ? "缺窗口" : "No max")
        : modelInputAvailable
          ? numberFormatter.format(modelInputTokens)
          : "--",
      displayValue: modelInputLimitMissing
        ? "!"
        : modelInputAvailable
          ? formatTokenStatusRingCompact(modelInputTokens, compactNumberFormatter)
          : "--",
      meta: modelInputMetaLine,
      title: modelInputTitle,
      titleLines: modelInputTitleLines,
      percent: clampPercent(modelInputLimitMissing ? 0 : modelInputPercent),
      tone: "modelInput",
    },
    {
      key: "compression",
      label: lang === "zh" ? "压缩状态" : "Compression",
      value: compression ? `${compressionCurrentPercent}%` : "--",
      meta: compression ? tokenCompressionLevelLabel : compressionUnavailableLine,
      title: tokenStatusCompressionTitle,
      titleLines: tokenStatusCompressionTitleLines,
      percent: clampPercent(compression ? compressionCurrentPercent : 0),
      tone: "compression",
    },
    {
      key: "speed",
      label: t("tokenSpeed"),
      value: tokenSpeedValue,
      meta: tokenSpeedMeta,
      title: tokenSpeedTitle,
      titleLines: tokenSpeedTitleLines,
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
