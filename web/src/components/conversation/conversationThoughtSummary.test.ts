import { describe, expect, it } from "vitest";

import {
  isThoughtScrollAtBottom,
  resolveThoughtStreamingSummary,
  thoughtScrollDistanceFromBottom,
} from "./conversationThoughtSummary";

describe("resolveThoughtStreamingSummary", () => {
  it("returns the last non-empty line of a multi-line thought", () => {
    const summary = resolveThoughtStreamingSummary("先看入口。\n中间跳过。\n  最新一句思考。  ");
    expect(summary).toEqual({ key: "2", text: "最新一句思考。" });
  });

  it("skips trailing empty lines produced by streaming whitespace", () => {
    const summary = resolveThoughtStreamingSummary("第一句。\n\n   \n");
    expect(summary).toEqual({ key: "0", text: "第一句。" });
  });

  it("normalizes CRLF line endings before scanning", () => {
    const summary = resolveThoughtStreamingSummary("第一句。\r\n最新一句。\r\n");
    expect(summary).toEqual({ key: "1", text: "最新一句。" });
  });

  it("keeps the single-line thought as-is and trims it", () => {
    expect(resolveThoughtStreamingSummary("  唯一一句。 ")).toEqual({ key: "0", text: "唯一一句。" });
  });

  it("returns null for empty or whitespace-only text", () => {
    expect(resolveThoughtStreamingSummary("")).toBeNull();
    expect(resolveThoughtStreamingSummary("   \n  \n")).toBeNull();
  });

  it("keeps the line key stable so unchanged lines do not re-sync the viewport", () => {
    const first = resolveThoughtStreamingSummary("开头。\n追加前一句。");
    const second = resolveThoughtStreamingSummary("开头。\n追加前一句。更多内容。");
    expect(first?.key).toBe("1");
    expect(second?.key).toBe("1");
    expect(second?.text).toBe("追加前一句。更多内容。");
  });
});

describe("isThoughtScrollAtBottom", () => {
  it("treats exact bottom as following", () => {
    expect(isThoughtScrollAtBottom({ clientHeight: 100, scrollHeight: 400, scrollTop: 300 })).toBe(true);
  });

  it("keeps following within the 2px lock tolerance", () => {
    expect(isThoughtScrollAtBottom({ clientHeight: 100, scrollHeight: 400, scrollTop: 298 })).toBe(true);
  });

  it("stops following once the user scrolls away from the bottom", () => {
    expect(isThoughtScrollAtBottom({ clientHeight: 100, scrollHeight: 400, scrollTop: 297.5 })).toBe(false);
    expect(isThoughtScrollAtBottom({ clientHeight: 100, scrollHeight: 400, scrollTop: 0 })).toBe(false);
  });

  it("returns true when the content never overflows the viewport", () => {
    expect(isThoughtScrollAtBottom({ clientHeight: 200, scrollHeight: 120, scrollTop: 0 })).toBe(true);
  });

  it("never reports a negative distance", () => {
    expect(thoughtScrollDistanceFromBottom({ clientHeight: 400, scrollHeight: 300, scrollTop: 50 })).toBe(0);
  });
});
