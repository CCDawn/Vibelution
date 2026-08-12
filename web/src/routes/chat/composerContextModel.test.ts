import { describe, expect, it } from "vitest";

import {
  buildComposerContextRingModel,
  formatCompactTokenCount,
  resolveComposerSegmentHitKind,
} from "./composerContextModel";

describe("composerContextModel", () => {
  it("formats compact token counts", () => {
    expect(formatCompactTokenCount(980)).toBe("980");
    expect(formatCompactTokenCount(1500)).toBe("1.5K");
    expect(formatCompactTokenCount(12000)).toBe("12K");
    expect(formatCompactTokenCount(2_500_000)).toBe("2.5M");
  });

  it("resolves hit kinds from policy and observed status", () => {
    expect(resolveComposerSegmentHitKind({
      cachePolicy: "never_cache",
      observedStatus: "hit",
      status: "hit",
      observedCachedInputTokens: 10,
      observedMissedInputTokens: 0,
    })).toBe("never");
    expect(resolveComposerSegmentHitKind({
      cachePolicy: "stable",
      observedStatus: "partial_hit",
      status: "",
      observedCachedInputTokens: 4,
      observedMissedInputTokens: 4,
    })).toBe("miss");
    expect(resolveComposerSegmentHitKind({
      cachePolicy: "stable",
      observedStatus: "cache_hit",
      status: "miss",
      observedCachedInputTokens: 0,
      observedMissedInputTokens: 0,
    })).toBe("hit");
    expect(resolveComposerSegmentHitKind({
      cachePolicy: "stable",
      observedStatus: "",
      status: "",
      observedCachedInputTokens: 0,
      observedMissedInputTokens: 12,
    })).toBe("miss");
  });

  it("builds ring model with usage and segment shares", () => {
    const model = buildComposerContextRingModel({
      usageUsed: 42000,
      usageLimit: 200000,
      hitPercent: 67.4,
      detailAvailable: true,
      lang: "zh",
      segments: [
        {
          key: "system",
          label: "系统",
          tokens: 2000,
          cachePolicy: "stable",
          observedStatus: "hit",
        },
        {
          key: "tools",
          label: "工具",
          tokens: 3000,
          cachePolicy: "stable",
          observedStatus: "miss",
        },
        {
          key: "turn",
          label: "本轮",
          tokens: 5000,
          cachePolicy: "never_cache",
          observedStatus: "miss",
        },
      ] as never,
    });
    expect(model.empty).toBe(false);
    expect(model.usagePercent).toBe(21);
    expect(model.hitPercent).toBe(67);
    expect(model.usedLabel).toBe("42K / 200K");
    expect(model.detailAvailable).toBe(true);
    expect(model.segments).toHaveLength(3);
    expect(model.segments[0]?.hit).toBe("hit");
    expect(model.segments[1]?.hit).toBe("miss");
    expect(model.segments[2]?.hit).toBe("never");
    expect(model.segments.reduce((sum, segment) => sum + segment.pct, 0)).toBeCloseTo(100, 0);
  });

  it("marks empty when no usage and no segments", () => {
    const model = buildComposerContextRingModel({
      usageUsed: 0,
      usageLimit: 0,
      hitPercent: 0,
      detailAvailable: false,
      lang: "en",
      segments: [],
    });
    expect(model.empty).toBe(true);
    expect(model.segments).toEqual([]);
  });
});
