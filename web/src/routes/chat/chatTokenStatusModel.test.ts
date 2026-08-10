import { describe, expect, it } from "vitest";

import {
  buildChatTokenStatusViewModel,
  formatTokenStatusRingCompact,
} from "./chatTokenStatusModel";

describe("formatTokenStatusRingCompact", () => {
  it("keeps short latin compact values", () => {
    const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
    expect(formatTokenStatusRingCompact(1200, compact)).toMatch(/1(\.2)?K/i);
  });

  it("falls back from wide zh compact like 2.3万 so the 28px ring stays single-line", () => {
    const compact = new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 });
    expect(compact.format(23000)).toContain("万");
    const ring = formatTokenStatusRingCompact(23000, compact);
    expect(ring).not.toMatch(/万/);
    expect(ring.length).toBeLessThanOrEqual(4);
    expect(ring).toMatch(/23\s*K/i);
  });
});

describe("chatTokenStatusModel", () => {
  it("shows missing cache telemetry instead of a false zero hit", () => {
    const model = buildChatTokenStatusViewModel({
      detail: {
        llmUsage: {
          source: "provider_usage",
          inputTokens: 1200,
          outputTokens: 100,
          totalTokens: 1300,
          cachedInputTokens: 0,
          cacheCreationInputTokens: 0,
          uncachedInputTokens: 0,
          cacheHitRate: 0,
          cacheUsageObserved: false,
          cacheUsageMissingReason: "provider_cache_usage_missing",
        },
        cacheUsage: {
          source: "missing",
          cacheUsageObserved: false,
          cacheUsageMissingReason: "provider_cache_usage_missing",
          turnInputTokens: 0,
          turnCachedInputTokens: 0,
          turnCacheHitRate: 0,
        },
      } as never,
      lastCacheComposition: null,
      lastContextComposition: { limitTokens: 200000, totalTokens: 1200 } as never,
      compression: null,
      cache: {
        cacheDetailAvailable: false,
        cacheCompositionPercent: 0,
        providerCachedInputTokens: 0,
        providerCacheInputTokens: 0,
        cacheCompositionSummary: "cache missing",
        cacheDetailOpenLabel: "View cache",
        cacheCompositionTitle: "cache title",
      },
      tokenSpeedTracker: null,
      activeSessionId: "s1",
      groupPanelActive: false,
      sessionStateValue: "idle",
      sessionStateLabel: "Idle",
      sessionStateLine: "ready",
      lang: "zh",
      t: ((key: string) => key) as never,
      numberFormatter: new Intl.NumberFormat("zh-CN"),
      compactNumberFormatter: new Intl.NumberFormat("zh-CN", { notation: "compact" }),
      locale: "zh-CN",
      formatTime: (value) => value,
    });

    expect(model.tokenStatusCacheTitle).toBe("cacheHitMissing");
    expect(model.llmUsageLine).toBe("1,200 · cacheHitMissing");
    expect(model.llmUsageTitle).toContain("cacheHitMissing");
    expect(model.llmUsageLine).not.toContain("缓 0");
  });

  it("builds cache/model/compression/speed metrics from provider usage", () => {
    const model = buildChatTokenStatusViewModel({
      detail: {
        llmUsage: {
          source: "provider_usage",
          inputTokens: 1200,
          outputTokens: 300,
          totalTokens: 1500,
          cachedInputTokens: 400,
          cacheCreationInputTokens: 0,
          uncachedInputTokens: 800,
          cacheHitRate: 0.33,
        },
        cacheUsage: {
          source: "provider_usage",
          turnInputTokens: 1000,
          turnCachedInputTokens: 400,
          turnCacheHitRate: 0.4,
        },
      } as never,
      lastCacheComposition: {
        calibratedInputTokens: 1100,
        calibratedCachedInputTokens: 350,
        inputTokens: 1000,
        cachedInputTokens: 300,
      } as never,
      lastContextComposition: {
        limitTokens: 200000,
        totalTokens: 5000,
      } as never,
      compression: {
        enabled: true,
        currentTokens: 8000,
        effectiveTokenLimit: 100000,
        contextWindowLimit: 200000,
        usageRatio: 0.08,
        currentLevel: "normal",
        source: "runtime_state",
        policySource: "global",
        strategy: {
          levels: [],
          preserveErrors: true,
          errorProtectionKeywords: [],
          summaryStorage: "",
          algorithm: "",
        },
        lastCompression: null,
        compressionCount: 0,
        updatedAt: "",
      } as never,
      cache: {
        cacheDetailAvailable: true,
        cacheCompositionPercent: 40,
        providerCachedInputTokens: 350,
        providerCacheInputTokens: 1100,
        cacheCompositionSummary: "true 40%",
        cacheDetailOpenLabel: "View cache",
        cacheCompositionTitle: "cache title",
      },
      tokenSpeedTracker: null,
      activeSessionId: "s1",
      groupPanelActive: false,
      sessionStateValue: "idle",
      sessionStateLabel: "Idle",
      sessionStateLine: "ready",
      lang: "en",
      t: ((key: string) => key) as never,
      numberFormatter: new Intl.NumberFormat("en-US"),
      compactNumberFormatter: new Intl.NumberFormat("en-US", { notation: "compact" }),
      locale: "en-US",
      formatTime: (value) => value,
    });

    expect(model.tokenStatusMetrics).toHaveLength(4);
    expect(model.tokenStatusMetrics.map((item) => item.key)).toEqual([
      "cache",
      "modelInput",
      "compression",
      "speed",
    ]);
    expect(model.modelInputAvailable).toBe(true);
    expect(model.modelInputTokens).toBe(1100);
    expect(model.tokenStatusMetrics[0]?.value).toBe("40%");
    expect(model.tokenStatusMetrics[1]?.tone).toBe("modelInput");
    expect(model.tokenStatusMetrics[1]?.value).not.toBe("缺窗口");
    expect(model.tokenStatusMetrics[2]?.value).toBe("8%");
    expect(model.llmUsageTitle).toContain("out");
  });

  it("fails closed when max context window is missing instead of inventing a default", () => {
    const model = buildChatTokenStatusViewModel({
      detail: {
        llmUsage: {
          source: "provider_usage",
          inputTokens: 1200,
          outputTokens: 100,
          totalTokens: 1300,
          cachedInputTokens: 0,
        },
        contextUsage: {
          used: 1200,
          limit: 0,
          limitSource: "missing",
          estimatedTokens: 1200,
          messageCount: 1,
          userMessageCount: 1,
          assistantMessageCount: 0,
          toolCallCount: 0,
          source: "conversation_ledger",
        },
      } as never,
      lastCacheComposition: {
        calibratedInputTokens: 1200,
        calibratedCachedInputTokens: 0,
        inputTokens: 1200,
        cachedInputTokens: 0,
        cacheHitRate: 0,
      } as never,
      lastContextComposition: {
        limitTokens: 0,
        limitSource: "missing",
        totalTokens: 1200,
      } as never,
      compression: null,
      cache: {
        cacheDetailAvailable: true,
        cacheCompositionPercent: 0,
        providerCachedInputTokens: 0,
        providerCacheInputTokens: 1200,
        cacheCompositionSummary: "true 0%",
        cacheDetailOpenLabel: "View cache",
        cacheCompositionTitle: "cache title",
      },
      tokenSpeedTracker: null,
      activeSessionId: "s1",
      groupPanelActive: false,
      sessionStateValue: "idle",
      sessionStateLabel: "Idle",
      sessionStateLine: "ready",
      lang: "zh",
      t: ((key: string) => key) as never,
      numberFormatter: new Intl.NumberFormat("zh-CN"),
      compactNumberFormatter: new Intl.NumberFormat("zh-CN", { notation: "compact" }),
      locale: "zh-CN",
      formatTime: (value) => value,
    });

    const inputMetric = model.tokenStatusMetrics.find((item) => item.key === "modelInput");
    expect(inputMetric?.value).toBe("缺窗口");
    expect(inputMetric?.displayValue).toBe("!");
    expect(inputMetric?.meta).toContain("禁止默认兜底");
    expect(inputMetric?.title).toContain("禁止默认兜底");
    expect(model.modelInputMetaLine).toContain("禁止默认兜底");
  });

  it("labels an unmaterialized Agent compression policy instead of inherited global", () => {
    const model = buildChatTokenStatusViewModel({
      detail: null,
      lastCacheComposition: null,
      lastContextComposition: null,
      compression: {
        enabled: false,
        policyMode: "unmaterialized",
        policySource: "migration_required",
        currentTokens: 9181,
        effectiveTokenLimit: 500000,
        contextWindowLimit: 1000000,
        usageRatio: 0.0184,
        currentLevel: "normal",
        source: "runtime_state",
        compressionCount: 0,
        lastCompression: null,
        strategy: {
          levels: [],
          preserveErrors: true,
          errorProtectionKeywords: [],
          summaryStorage: "state_memory",
          algorithm: "",
        },
        updatedAt: "",
      } as never,
      cache: {
        cacheDetailAvailable: false,
        cacheCompositionPercent: 0,
        providerCachedInputTokens: 0,
        providerCacheInputTokens: 0,
        cacheCompositionSummary: "",
        cacheDetailOpenLabel: "",
        cacheCompositionTitle: "",
      },
      tokenSpeedTracker: null,
      activeSessionId: "session-luna",
      groupPanelActive: false,
      sessionStateValue: "idle",
      sessionStateLabel: "空闲",
      sessionStateLine: "ready",
      lang: "zh",
      t: ((key: string) => key === "compressionDisabled" ? "未启用" : key) as never,
      numberFormatter: new Intl.NumberFormat("zh-CN"),
      compactNumberFormatter: new Intl.NumberFormat("zh-CN", { notation: "compact" }),
      locale: "zh-CN",
      formatTime: (value) => value,
    });

    const compressionMetric = model.tokenStatusMetrics.find((item) => item.key === "compression");
    expect(compressionMetric?.value).toBe("2%");
    expect(compressionMetric?.meta).toContain("未启用");
    expect(compressionMetric?.title).toContain("Agent 策略未物化");
    expect(compressionMetric?.title).not.toContain("继承全局策略");
    expect(compressionMetric?.title).not.toContain("runtime_state");
    expect(compressionMetric?.title).not.toContain("light:");
    expect(compressionMetric?.titleLines?.length).toBeLessThanOrEqual(3);
  });

  it("keeps token hover titles short and high-value only", () => {
    const model = buildChatTokenStatusViewModel({
      detail: {
        llmUsage: {
          source: "provider_usage",
          inputTokens: 1200,
          outputTokens: 300,
          totalTokens: 1500,
          cachedInputTokens: 400,
          cacheCreationInputTokens: 0,
          uncachedInputTokens: 800,
        },
        cacheUsage: {
          source: "provider_usage",
          turnInputTokens: 1000,
          turnCachedInputTokens: 400,
          turnCacheHitRate: 0.4,
        },
      } as never,
      lastCacheComposition: {
        calibratedInputTokens: 1100,
        calibratedCachedInputTokens: 350,
        inputTokens: 1000,
        cachedInputTokens: 300,
      } as never,
      lastContextComposition: {
        limitTokens: 200000,
        totalTokens: 5000,
      } as never,
      compression: {
        enabled: true,
        currentTokens: 311385,
        effectiveTokenLimit: 262144,
        contextWindowLimit: 262144,
        usageRatio: 1,
        currentLevel: "emergency",
        source: "runtime_state",
        policySource: "global",
        strategy: {
          levels: [
            { level: "light", thresholdRatio: 0.6, thresholdTokens: 157286 },
            { level: "standard", thresholdRatio: 0.8, thresholdTokens: 209715 },
            { level: "deep", thresholdRatio: 0.9, thresholdTokens: 235929 },
            { level: "emergency", thresholdRatio: 0.95, thresholdTokens: 249036 },
          ],
          preserveErrors: true,
          errorProtectionKeywords: [],
          summaryStorage: "",
          algorithm: "",
        },
        lastCompression: {
          triggerSource: "manual",
          level: "emergency",
          beforeTokens: 19058,
          afterTokens: 18925,
          savedTokens: 133,
          timestamp: "2026-01-01T00:00:00Z",
        },
        compressionCount: 1,
        updatedAt: "2026-01-01T00:00:00Z",
      } as never,
      cache: {
        cacheDetailAvailable: true,
        cacheCompositionPercent: 99,
        providerCachedInputTokens: 350,
        providerCacheInputTokens: 1100,
        cacheCompositionSummary: "true 99%",
        cacheDetailOpenLabel: "View cache",
        cacheCompositionTitle: "cache title long dump",
      },
      tokenSpeedTracker: null,
      activeSessionId: "s1",
      groupPanelActive: false,
      sessionStateValue: "idle",
      sessionStateLabel: "Idle",
      sessionStateLine: "ready long state line",
      lang: "zh",
      t: ((key: string) => key) as never,
      numberFormatter: new Intl.NumberFormat("zh-CN"),
      compactNumberFormatter: new Intl.NumberFormat("zh-CN", { notation: "compact" }),
      locale: "zh-CN",
      formatTime: (value) => value,
    });

    for (const metric of model.tokenStatusMetrics) {
      expect((metric.titleLines ?? []).length).toBeGreaterThan(0);
      expect((metric.titleLines ?? []).length).toBeLessThanOrEqual(3);
      expect(metric.title).not.toMatch(/light:\s*60%/);
      expect(metric.title).not.toContain("runtime_state");
    }
    const compression = model.tokenStatusMetrics.find((item) => item.key === "compression");
    expect(compression?.titleLines?.[0]).toMatch(/311/);
    expect(compression?.title).toContain("主动压缩");
    expect(compression?.title).not.toContain("cache title long dump");
  });

  it("labels compression as active-session-only when runtime does not match selection", () => {
    const model = buildChatTokenStatusViewModel({
      detail: null,
      lastCacheComposition: null,
      lastContextComposition: null,
      compression: null,
      runtimeMatchesSelectedSession: false,
      cache: {
        cacheDetailAvailable: false,
        cacheCompositionPercent: 0,
        providerCachedInputTokens: 0,
        providerCacheInputTokens: 0,
        cacheCompositionSummary: "",
        cacheDetailOpenLabel: "",
        cacheCompositionTitle: "",
      },
      tokenSpeedTracker: null,
      activeSessionId: "session-other",
      groupPanelActive: false,
      sessionStateValue: "idle",
      sessionStateLabel: "空闲",
      sessionStateLine: "ready",
      lang: "zh",
      t: ((key: string) => key) as never,
      numberFormatter: new Intl.NumberFormat("zh-CN"),
      compactNumberFormatter: new Intl.NumberFormat("zh-CN", { notation: "compact" }),
      locale: "zh-CN",
      formatTime: (value) => value,
    });

    const compressionMetric = model.tokenStatusMetrics.find((item) => item.key === "compression");
    expect(compressionMetric?.value).toBe("--");
    expect(compressionMetric?.meta).toBe("compressionScopeInactiveSession");
    expect(compressionMetric?.title).toContain("compressionScopeInactiveSessionHint");
    expect(compressionMetric?.title).not.toContain("loadingContext");
  });
});
