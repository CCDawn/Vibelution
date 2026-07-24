import { describe, expect, it } from "vitest";

import { buildChatTokenStatusViewModel } from "./chatTokenStatusModel";

describe("chatTokenStatusModel", () => {
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
});
