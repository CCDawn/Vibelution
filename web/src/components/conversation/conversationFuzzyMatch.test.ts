import { describe, expect, it } from "vitest";

import {
  containsCjk,
  rankByScore,
  SCORE_NONE,
  SCORE_PREFIX,
  SCORE_SUBSEQUENCE,
  SCORE_SUBSTRING,
  scoreMatch,
} from "./conversationFuzzyMatch";

describe("scoreMatch", () => {
  it("ranks prefix above substring above subsequence, and rejects the rest", () => {
    expect(scoreMatch("road", "roadmap 2026")).toBe(SCORE_PREFIX);
    expect(scoreMatch("map 2", "roadmap 2026")).toBe(SCORE_SUBSTRING);
    expect(scoreMatch("rm26", "roadmap 2026")).toBe(SCORE_SUBSEQUENCE);
    expect(scoreMatch("zzz", "roadmap 2026")).toBe(SCORE_NONE);
    expect(SCORE_PREFIX).toBeLessThan(SCORE_SUBSTRING);
    expect(SCORE_SUBSTRING).toBeLessThan(SCORE_SUBSEQUENCE);
    expect(SCORE_SUBSEQUENCE).toBeLessThan(SCORE_NONE);
  });

  it("keeps CJK on the prefix and substring tiers only", () => {
    expect(scoreMatch("文件", "文件管理指南")).toBe(SCORE_PREFIX);
    expect(scoreMatch("管理", "项目文件管理指南")).toBe(SCORE_SUBSTRING);
  });

  it("never awards CJK a subsequence hit when characters are scattered", () => {
    // "文" and "件" both appear (in order, even), but never adjacently: the
    // subsequence tier would false-positive, so CJK must not match at all.
    expect(scoreMatch("文件", "把文散着的件混起来")).toBe(SCORE_NONE);
    // A CJK haystack closes the tier for ASCII queries too.
    expect(scoreMatch("wj", "把文散着的件混起来")).toBe(SCORE_NONE);
  });

  it("still allows English subsequence hits as the lowest tier", () => {
    expect(scoreMatch("rm26", "roadmap 2026")).toBe(SCORE_SUBSEQUENCE);
    expect(scoreMatch("bsg", "brainstorming")).toBe(SCORE_SUBSEQUENCE);
  });

  it("treats an empty query as a top-tier tie so callers keep input order", () => {
    expect(scoreMatch("", "任意文本")).toBe(SCORE_PREFIX);
    expect(scoreMatch("", "anything")).toBe(SCORE_PREFIX);
  });
});

describe("containsCjk", () => {
  it("covers the common CJK ranges: hanzi, kana, hangul, and astral ideographs", () => {
    expect(containsCjk("中文")).toBe(true);
    expect(containsCjk("ファイル")).toBe(true);
    expect(containsCjk("한국어")).toBe(true);
    expect(containsCjk("𠀀")).toBe(true);
    expect(containsCjk("plain English 123")).toBe(false);
    expect(containsCjk("")).toBe(false);
  });
});

describe("rankByScore", () => {
  it("orders prefix, substring, then subsequence and drops non-matches", () => {
    const items = [
      "scattered r-o-a-d notes",
      "roadmap planning",
      "project roadmap 2026",
      "unrelated entry",
    ];
    expect(rankByScore(items, "road", (item) => item)).toEqual([
      "roadmap planning",
      "project roadmap 2026",
      "scattered r-o-a-d notes",
    ]);
  });

  it("keeps the caller's order for equal scores", () => {
    const items = ["beta roadmap", "alpha roadmap", "gamma roadmap"];
    expect(rankByScore(items, "road", (item) => item)).toEqual(items);
  });
});
