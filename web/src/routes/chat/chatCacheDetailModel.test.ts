import { describe, expect, it } from "vitest";

import { buildChatCacheDetailViewModel } from "./chatCacheDetailModel";

describe("chatCacheDetailModel", () => {
  it("builds true-cache donut segments from provider composition", () => {
    const model = buildChatCacheDetailViewModel({
      detail: undefined,
      lastCacheComposition: {
        source: "provider_usage",
        inputTokens: 100,
        cachedInputTokens: 40,
        uncachedInputTokens: 60,
        cacheHitRate: 0.4,
        calibratedInputTokens: 100,
        calibratedCachedInputTokens: 40,
        cacheCreationInputTokens: 0,
      } as never,
      lastCacheDiagnostics: {
        upperBoundInputTokens: 100,
        upperBoundCachedInputTokens: 50,
        upperBoundCacheHitRate: 0.5,
      } as never,
      lang: "en",
      t: ((key: string) => key) as never,
      numberFormatter: new Intl.NumberFormat("en-US"),
    });
    expect(model.providerCacheInputTokens).toBe(100);
    expect(model.providerCachedInputTokens).toBe(40);
    expect(model.cacheCompositionPercent).toBe(40);
    expect(model.trueCacheDonutSegments.length).toBeGreaterThan(0);
    expect(model.cacheDetailAvailable).toBe(true);
  });
});
