import { describe, expect, it } from "vitest";

import {
  formatTurnTokenCount,
  resolveConversationTurnUsageLabel,
} from "./conversationTurnUsageLabel";

const USAGE = {
  inputTokens: 12_400,
  completionTokens: 860,
  totalTokens: 13_260,
  cachedInputTokens: 8_000,
  elapsedMs: 4_200,
  tokensPerSecond: 204.8,
};

describe("resolveConversationTurnUsageLabel", () => {
  it("returns null without a measured total", () => {
    expect(resolveConversationTurnUsageLabel(null, "zh")).toBeNull();
    expect(resolveConversationTurnUsageLabel(undefined, "zh")).toBeNull();
    expect(resolveConversationTurnUsageLabel({ ...USAGE, totalTokens: 0 }, "zh")).toBeNull();
    expect(resolveConversationTurnUsageLabel({ ...USAGE, totalTokens: Number.NaN }, "zh")).toBeNull();
  });

  it("renders a compact total with a localized breakdown", () => {
    const label = resolveConversationTurnUsageLabel(USAGE, "zh");
    expect(label?.label).toBe(`${formatTurnTokenCount(USAGE.totalTokens, "zh")} tokens`);
    expect(label?.titleLines).toEqual([
      `输入 ${formatTurnTokenCount(USAGE.inputTokens, "zh")}`,
      `输出 ${formatTurnTokenCount(USAGE.completionTokens, "zh")}`,
      `缓存 ${formatTurnTokenCount(USAGE.cachedInputTokens, "zh")}`,
      "速度 205 tok/s",
    ]);
  });

  it("omits unmeasured breakdown rows instead of inventing zeros", () => {
    const label = resolveConversationTurnUsageLabel(
      { ...USAGE, cachedInputTokens: 0, tokensPerSecond: null },
      "en",
    );
    expect(label?.titleLines).toEqual([
      `Input ${formatTurnTokenCount(USAGE.inputTokens, "en")}`,
      `Output ${formatTurnTokenCount(USAGE.completionTokens, "en")}`,
    ]);
  });
});
