import { describe, expect, it } from "vitest";

import {
  CONVERSATION_SUBAGENT_COLOR_BUCKET_COUNT,
  conversationSubagentAccentColor,
  conversationSubagentAccentStyle,
  conversationSubagentColorBucket,
  conversationSubagentColorHash,
} from "./conversationSubagentColor";

describe("conversationSubagentColor", () => {
  it("hashes names into the unsigned 32-bit space deterministically", () => {
    expect(conversationSubagentColorHash("researcher")).toBe(conversationSubagentColorHash("researcher"));
    expect(conversationSubagentColorHash("researcher"))
      .toBe(conversationSubagentColorHash("researcher") % 2 ** 32);
    expect(conversationSubagentColorHash("")).toBe(0);
    // The accumulate must wrap like ZCode's: values above 2^31 stay unsigned.
    const longName = "subagent-".repeat(40);
    expect(conversationSubagentColorHash(longName)).toBeLessThan(2 ** 32);
    expect(conversationSubagentColorHash(longName)).toBeGreaterThanOrEqual(0);
  });

  it("maps a name onto one stable bucket in [0, 8)", () => {
    expect(CONVERSATION_SUBAGENT_COLOR_BUCKET_COUNT).toBe(8);
    for (const name of ["researcher", "inspector", "reviewer", "实现代理", "implement-agent"]) {
      const bucket = conversationSubagentColorBucket(name);
      expect(bucket).toBeGreaterThanOrEqual(0);
      expect(bucket).toBeLessThan(8);
      expect(Number.isInteger(bucket)).toBe(true);
      expect(conversationSubagentColorBucket(name)).toBe(bucket);
    }
    expect(conversationSubagentColorBucket("researcher"))
      .toBe(conversationSubagentColorHash("researcher") % 8);
  });

  it("keeps empty names on bucket 0 and spreads distinct names across buckets", () => {
    expect(conversationSubagentColorBucket("")).toBe(0);
    expect(conversationSubagentColorBucket("   ")).toBe(0);
    const buckets = new Set(
      ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "research", "review"]
        .map((name) => conversationSubagentColorBucket(name)),
    );
    expect(buckets.size).toBeGreaterThan(1);
  });

  it("derives every bucket from the theme accent token with a 45-degree hue rotation", () => {
    for (let bucket = 0; bucket < CONVERSATION_SUBAGENT_COLOR_BUCKET_COUNT; bucket += 1) {
      const accent = conversationSubagentAccentColor(bucket);
      expect(accent).toContain("var(--accent-cool)");
      expect(accent).toContain(`calc(h + ${bucket * 45}deg)`);
      // No literal colors: everything flows through the token.
      expect(accent).not.toContain("#");
    }
    expect(conversationSubagentAccentColor(7)).toContain("calc(h + 315deg)");
  });

  it("normalizes out-of-range buckets instead of leaking NaN", () => {
    expect(conversationSubagentAccentColor(8)).toBe(conversationSubagentAccentColor(0));
    expect(conversationSubagentAccentColor(-1)).toBe(conversationSubagentAccentColor(7));
    expect(conversationSubagentAccentColor(9)).toBe(conversationSubagentAccentColor(1));
  });

  it("exposes the accent as a --subagent-accent custom property payload", () => {
    const style = conversationSubagentAccentStyle(3);
    expect(style).toEqual({ "--subagent-accent": conversationSubagentAccentColor(3) });
  });
});
