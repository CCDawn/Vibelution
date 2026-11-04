import { describe, expect, it } from "vitest";

import type { TokenUsageRollup, TokenUsageSample } from "../../api/types";
import { buildComposerCacheUsageModel, type ComposerCacheUsageSnapshot } from "./composerCacheUsageModel";

function snapshot(session: Partial<TokenUsageRollup> = {}, last: TokenUsageSample = {
  source: "provider_usage", inputTokens: 900, cachedInputTokens: 0, cacheUsageObserved: true,
}): ComposerCacheUsageSnapshot {
  return {
    sessionTokenUsage: { inputTokens: 11000, cachedInputTokens: 100, cacheObservedInputTokens: 1000,
      cacheObservedCallCount: 2, cacheUnobservedCallCount: 1, callCount: 3, cacheUsageObserved: true,
      cacheUsageComplete: false, cacheHitRate: 0.5, ...session } as TokenUsageRollup,
    lastTokenUsage: last,
  };
}

describe("composer cache usage model", () => {
  it("weights observed input tokens and excludes missing calls and cache writes", () => {
    const result = buildComposerCacheUsageModel({ snapshot: snapshot({ cacheCreationInputTokens: 5000 }) });
    // Two observed calls: 100/100 and 0/900; one unknown 10000-token call.
    // The call average is 50%, and all-input weighting is 1%; neither is 10%.
    expect(result).toMatchObject({ state: "partial", sessionPercent: 10, lastCallPercent: 0,
      observedCalls: 2, totalCalls: 3 });
  });

  it("keeps an observed zero as ready even when all input was cache creation", () => {
    const result = buildComposerCacheUsageModel({ snapshot: snapshot({
      cachedInputTokens: 0, cacheObservedInputTokens: 100, cacheUnobservedCallCount: 0,
      cacheCreationInputTokens: 100, cacheUsageComplete: true, callCount: 2,
    }, { source: "provider_usage", inputTokens: 100, cachedInputTokens: 0,
      cacheCreationInputTokens: 100, cacheUsageObserved: true }) });
    expect(result).toMatchObject({ state: "ready", sessionPercent: 0, lastCallPercent: 0 });
  });

  it.each(["estimated", "missing"] as const)("counts %s calls as partial coverage without changing the observed rate", source => {
    const result = buildComposerCacheUsageModel({ snapshot: snapshot({
      inputTokens: 1000, cachedInputTokens: 25, cacheObservedInputTokens: 100,
      cacheObservedCallCount: 1, cacheUnobservedCallCount: 0, callCount: 2,
      estimatedCallCount: source === "estimated" ? 1 : 0, missingCallCount: source === "missing" ? 1 : 0,
    }) });
    expect(result).toMatchObject({ state: "partial", sessionPercent: 25, observedCalls: 1, totalCalls: 2 });
  });

  it("excludes not-called ledger records from actual-call coverage", () => {
    const result = buildComposerCacheUsageModel({ snapshot: snapshot({
      callCount: 3, notCalledCount: 1, cacheObservedCallCount: 2, cacheUnobservedCallCount: 0,
    }) });
    expect(result).toMatchObject({ state: "ready", observedCalls: 2, totalCalls: 2 });
  });

  it("distinguishes missing observations, no calls, and an absent or loading snapshot", () => {
    const missing = snapshot({ callCount: 2, cachedInputTokens: 0, cacheObservedInputTokens: 0,
      cacheObservedCallCount: 0, cacheUnobservedCallCount: 2, cacheUsageObserved: false },
    { source: "provider_usage", inputTokens: 100, cachedInputTokens: 0, cacheUsageObserved: false });
    expect(buildComposerCacheUsageModel({ snapshot: missing })).toMatchObject({
      state: "missing", sessionPercent: null, lastCallPercent: null, observedCalls: 0, totalCalls: 2,
    });
    expect(buildComposerCacheUsageModel({ snapshot: snapshot({ ...missing.sessionTokenUsage,
      callCount: 0, cacheUnobservedCallCount: 0 }, { source: "not_called" }) })).toMatchObject({
      state: "not_called", sessionPercent: null, lastCallPercent: null, totalCalls: 0,
    });
    expect(buildComposerCacheUsageModel({})).toMatchObject({ state: "missing", sessionPercent: null });
    expect(buildComposerCacheUsageModel({ loading: true })).toMatchObject({ state: "loading", sessionPercent: null });
    expect(buildComposerCacheUsageModel({ loading: true, error: true })).toMatchObject({ state: "error", sessionPercent: null });
  });

  it.each([undefined, null, 0, -1, NaN, Infinity, 1.5, "100", true, Number.MAX_SAFE_INTEGER + 1])(
    "does not turn an invalid observed-input denominator (%s) into zero percent", denominator => {
      const result = buildComposerCacheUsageModel({ snapshot: snapshot({
        cachedInputTokens: 0, cacheObservedInputTokens: denominator as number,
      }, { source: "provider_usage", inputTokens: denominator as number, cachedInputTokens: 0, cacheUsageObserved: true }) });
      expect(result).toMatchObject({ state: "missing", sessionPercent: null, lastCallPercent: null });
    },
  );

  it.each([undefined, null, -1, NaN, Infinity, 0.5, "10", true, 101, Number.MAX_SAFE_INTEGER + 1])(
    "rejects invalid cached-input counters (%s) for both rates", cached => {
      const result = buildComposerCacheUsageModel({ snapshot: snapshot({
        cachedInputTokens: cached as number, cacheObservedInputTokens: 100,
      }, { source: "provider_usage", inputTokens: 100, cachedInputTokens: cached as number, cacheUsageObserved: true }) });
      expect(result.sessionPercent).toBeNull();
      expect(result.lastCallPercent).toBeNull();
    },
  );

  it.each([
    ["provider_usage", true, 25], ["provider_usage", false, null], ["provider_usage", undefined, null],
    ["estimated", true, null], ["missing", true, null], ["not_called", true, null],
  ] as const)("last-call rate requires provider evidence (%s, observed=%s)", (source, observed, expected) => {
    expect(buildComposerCacheUsageModel({ snapshot: snapshot({}, {
      source, inputTokens: 200, cachedInputTokens: 50, cacheUsageObserved: observed,
    }) }).lastCallPercent).toBe(expected);
  });

  it("accepts explicit cache-read counts while never using cache-creation as last-call hits", () => {
    expect(buildComposerCacheUsageModel({ snapshot: snapshot({}, {
      source: "provider_usage", inputTokens: 200, cacheReadInputTokens: 50, cacheUsageObserved: true,
    }) }).lastCallPercent).toBe(25);
    expect(buildComposerCacheUsageModel({ snapshot: snapshot({}, {
      source: "provider_usage", inputTokens: 200, cacheCreationInputTokens: 200, cacheUsageObserved: true,
    }) }).lastCallPercent).toBeNull();
  });

  it("keeps confirmed numbers during an update or failure while exposing the error state", () => {
    const confirmed = snapshot();
    expect(buildComposerCacheUsageModel({ snapshot: confirmed, loading: true, updating: true })).toMatchObject({
      state: "partial", sessionPercent: 10, lastCallPercent: 0, updating: true,
    });
    expect(buildComposerCacheUsageModel({ snapshot: confirmed, error: true })).toMatchObject({
      state: "error", sessionPercent: 10, lastCallPercent: 0,
    });
  });
});
