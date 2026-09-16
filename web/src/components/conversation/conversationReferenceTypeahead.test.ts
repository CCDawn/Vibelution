import { describe, expect, it } from "vitest";

import type { SessionReferenceAttachment } from "../../api/types";
import {
  detectReferenceToken,
  filterReferenceTypeaheadOptions,
  MAX_REFERENCE_TYPEAHEAD_SUGGESTIONS,
  removeReferenceToken,
  type ReferenceTypeaheadOption,
} from "./conversationReferenceTypeahead";

function caretOf(text: string): number {
  const marker = text.indexOf("|");
  expect(marker).toBeGreaterThanOrEqual(0);
  return marker;
}

function detectMarked(text: string) {
  return detectReferenceToken(text.replace("|", ""), caretOf(text));
}

describe("detectReferenceToken", () => {
  it("arms at the very start of a draft (no preceding character needed)", () => {
    expect(detectReferenceToken("", 0)).toBeNull();
    expect(detectMarked("@|")).toEqual({ triggerIndex: 0, query: "", start: 0, end: 1 });
  });

  it("arms mid-sentence after whitespace and keeps the typed fragment as query", () => {
    expect(detectMarked("请看 @知识|")).toEqual({
      triggerIndex: 3,
      query: "知识",
      start: 3,
      end: 6,
    });
  });

  it("arms after CJK punctuation and after CJK characters", () => {
    expect(detectMarked("先总结，@文|")).toEqual({
      triggerIndex: 4,
      query: "文",
      start: 4,
      end: 6,
    });
    expect(detectMarked("你好@文件|")).toEqual({
      triggerIndex: 2,
      query: "文件",
      start: 2,
      end: 5,
    });
  });

  it("stays inert for email-like usage after an ASCII word", () => {
    expect(detectMarked("contact foo@bar|")).toBeNull();
    expect(detectMarked("a@b|")).toBeNull();
  });

  it("ends the token once a space is typed after @", () => {
    expect(detectMarked("@知识 |")).toBeNull();
    expect(detectMarked("x @a b|")).toBeNull();
  });

  it("tracks continuous typing by extending the query and replace range", () => {
    expect(detectMarked("@a|")).toEqual({ triggerIndex: 0, query: "a", start: 0, end: 2 });
    expect(detectMarked("@ab|")).toEqual({ triggerIndex: 0, query: "ab", start: 0, end: 3 });
    expect(detectMarked("@abc|")).toEqual({ triggerIndex: 0, query: "abc", start: 0, end: 4 });
  });

  it("deactivates when the caret moves out of the token", () => {
    expect(detectMarked("@abc foo|")).toBeNull();
    // Caret still inside the token (before its tail) keeps it armed with the
    // fragment up to the caret only.
    expect(detectMarked("@ab|c")).toEqual({ triggerIndex: 0, query: "ab", start: 0, end: 3 });
  });

  it("never arms during or after a very long pasted fragment", () => {
    const long = "x".repeat(65);
    expect(detectReferenceToken(`@${long}`, 66)).toBeNull();
    const within = "x".repeat(64);
    expect(detectReferenceToken(`@${within}`, 65)).toEqual({
      triggerIndex: 0,
      query: within,
      start: 0,
      end: 65,
    });
  });

  it("clamps out-of-range carets and never reads past the text", () => {
    expect(detectReferenceToken("@abc", 99)).toEqual({
      triggerIndex: 0,
      query: "abc",
      start: 0,
      end: 4,
    });
    expect(detectReferenceToken("@abc", -4)).toBeNull();
    expect(detectReferenceToken("", 3)).toBeNull();
  });

  it("prefers the closest @ when several exist", () => {
    expect(detectMarked("@a @b|")).toEqual({
      triggerIndex: 3,
      query: "b",
      start: 3,
      end: 5,
    });
  });
});

function option(id: string, title: string, meta?: string): ReferenceTypeaheadOption {
  const reference: SessionReferenceAttachment = {
    referenceId: id,
    kind: "knowledge_item",
    knowledgeBaseId: "kb",
    knowledgeItemId: id,
    title,
    createdAt: "2026-01-01T00:00:00Z",
  };
  return { id, title, meta, reference };
}

describe("filterReferenceTypeaheadOptions", () => {
  const options = [
    option("1", "检索指南", "知识库引用"),
    option("2", "Roadmap 2026", "planning"),
    option("3", "会议纪要", "roadmap"),
  ];

  it("returns the head of the list for an empty query", () => {
    expect(filterReferenceTypeaheadOptions(options, "")).toHaveLength(3);
    expect(filterReferenceTypeaheadOptions(options, "  ")[0]?.id).toBe("1");
  });

  it("matches title or meta case-insensitively (dialog parity)", () => {
    expect(filterReferenceTypeaheadOptions(options, "roadmap").map((item) => item.id)).toEqual(["2", "3"]);
    expect(filterReferenceTypeaheadOptions(options, "知识库").map((item) => item.id)).toEqual(["1"]);
  });

  it("caps results at the configured limit", () => {
    const many = Array.from({ length: 10 }, (_, index) => option(`id-${index}`, `文档 ${index}`));
    expect(filterReferenceTypeaheadOptions(many, "")).toHaveLength(MAX_REFERENCE_TYPEAHEAD_SUGGESTIONS);
    expect(filterReferenceTypeaheadOptions(many, "", 2)).toHaveLength(2);
  });
});

describe("removeReferenceToken", () => {
  it("removes the whole fragment and parks the caret at the removal point", () => {
    expect(removeReferenceToken("请看 @知识 这段", { triggerIndex: 3, query: "知识", start: 3, end: 6 })).toEqual({
      text: "请看  这段",
      caretIndex: 3,
    });
  });

  it("keeps one space when removal would glue words together", () => {
    expect(removeReferenceToken("前@知识后", { triggerIndex: 1, query: "知识", start: 1, end: 4 })).toEqual({
      text: "前 后",
      caretIndex: 2,
    });
  });

  it("trims cleanly at boundaries", () => {
    expect(removeReferenceToken("@a", { triggerIndex: 0, query: "a", start: 0, end: 2 })).toEqual({
      text: "",
      caretIndex: 0,
    });
    expect(removeReferenceToken(" @a", { triggerIndex: 1, query: "a", start: 1, end: 3 })).toEqual({
      text: " ",
      caretIndex: 1,
    });
  });
});
