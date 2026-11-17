import { describe, expect, it } from "vitest";

import {
  buildSessionSearchFields,
  normalizeSearchText,
  rankSessionSearch,
  scoreSearchTerm,
  splitSearchQuery,
  type SessionSearchTarget,
} from "./sessionSearch";

const sessions: SessionSearchTarget[] = [
  { id: "sess-alpha", title: "修复右栏宽度记忆", agentLabel: "opencode", keywords: ["workbench"] },
  { id: "sess-beta", title: "顶栏会话分组功能", agentLabel: "opencode", keywords: ["tabstrip"] },
  { id: "sess-gamma-7f3a", title: "调研 zcode 侧栏", agentLabel: "claude", keywords: ["research"] },
];

describe("sessionSearch", () => {
  it("normalizes case and trims whitespace", () => {
    expect(normalizeSearchText("  Fix: Chat/Rail  ")).toBe("fix: chat/rail");
  });

  it("splits the query on whitespace and drops empty entries", () => {
    expect(splitSearchQuery("  顶栏   分组 ")).toEqual(["顶栏", "分组"]);
  });

  it("returns the input order for an empty query", () => {
    expect(rankSessionSearch(sessions, "   ").map((item) => item.id)).toEqual([
      "sess-alpha",
      "sess-beta",
      "sess-gamma-7f3a",
    ]);
  });

  it("requires every term to match (AND semantics)", () => {
    const ranked = rankSessionSearch(sessions, "顶栏 分组");
    expect(ranked.map((item) => item.id)).toEqual(["sess-beta"]);
    expect(rankSessionSearch(sessions, "顶栏 zcode")).toEqual([]);
  });

  it("finds a session by a pasted id and ranks it first", () => {
    const ranked = rankSessionSearch(sessions, "sess-gamma-7f3a");
    expect(ranked[0]?.id).toBe("sess-gamma-7f3a");
  });

  it("ranks an id prefix above a title match", () => {
    const ranked = rankSessionSearch(sessions, "sess-");
    expect(ranked.map((item) => item.id)).toEqual([
      "sess-alpha",
      "sess-beta",
      "sess-gamma-7f3a",
    ]);
  });

  it("scores field classes in descending intent", () => {
    const fields = buildSessionSearchFields({
      id: "sess-1",
      title: "rail width memory",
      agentLabel: "opencode",
      keywords: ["workbench"],
    });
    expect(scoreSearchTerm(fields, "sess-1")).toBe(200);
    expect(scoreSearchTerm(fields, "rail")).toBe(120);
    expect(scoreSearchTerm(fields, "width")).toBe(90);
    expect(scoreSearchTerm(fields, "workbench")).toBe(40);
    expect(scoreSearchTerm(fields, "opencode")).toBe(30);
    expect(scoreSearchTerm(fields, "missing")).toBe(0);
  });

  it("keeps original order when scores tie", () => {
    const items: SessionSearchTarget[] = [
      { id: "a", title: "same subject one" },
      { id: "b", title: "same subject two" },
    ];
    expect(rankSessionSearch(items, "same subject").map((item) => item.id)).toEqual(["a", "b"]);
  });

  it("does not mutate the input array", () => {
    const before = [...sessions];
    rankSessionSearch(sessions, "rail");
    expect(sessions).toEqual(before);
  });
});
