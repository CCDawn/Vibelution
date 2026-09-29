import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import {
  buildConversationFindIndex,
  buildConversationFindMessageSignature,
  collectConversationFindSegments,
  createConversationFindIndexCache,
  normalizeConversationFindQuery,
  resolveConversationFindActiveIndex,
  resolveConversationFindJumpPlan,
  stepConversationFindActiveIndex,
} from "./conversationFindIndex";

function userMessage(id: string, content: string): ConversationMessage {
  return {
    id,
    role: "user",
    timestamp: "2026-09-29T10:00:00Z",
    content,
  };
}

function assistantMessage(
  id: string,
  items: Array<
    | { kind: "answer"; id: string; revision?: number; text: string }
    | { kind: "reasoning"; id: string; revision?: number; text: string }
  >,
  status: "completed" | "running" = "completed",
): ConversationMessage {
  return {
    id,
    role: "assistant",
    timestamp: "2026-09-29T10:00:05Z",
    turnId: `${id}-turn`,
    status,
    turnItems: items.map((item, index) => ({
      id: item.id,
      itemId: item.id,
      version: 3 as const,
      sessionId: "session-1",
      turnId: `${id}-turn`,
      type: item.kind === "reasoning" ? ("reasoning" as const) : ("agent_message" as const),
      ...(item.kind === "reasoning" ? {} : { phase: "final_answer" as const }),
      status: "completed" as const,
      revision: item.revision ?? 1,
      sequence: index,
      text: item.text,
    })),
  };
}

describe("conversation find index", () => {
  it("covers all three segment kinds: user, assistant body and reasoning", () => {
    const messages = [
      userMessage("u1", "帮我核对部署流程"),
      assistantMessage("a1", [
        { kind: "reasoning", id: "r1", text: "部署流程包含构建与发布两个阶段" },
        { kind: "answer", id: "m1", text: "部署流程如下：先构建再发布。" },
      ]),
    ];
    const index = buildConversationFindIndex(messages, "部署流程");
    expect(index.matchCount).toBe(3);
    expect(index.matchedRowCount).toBe(2);
    expect(index.matches.map((match) => match.kind)).toEqual(["user", "reasoning", "assistant"]);
    expect(index.matches.map((match) => match.messageId)).toEqual(["u1", "a1", "a1"]);
  });

  it("matches case-insensitively with plain substring semantics", () => {
    const messages = [
      userMessage("u1", "Retry the Deploy step"),
      assistantMessage("a1", [{ kind: "answer", id: "m1", text: "DEPLOY finished. deploy again." }]),
    ];
    const index = buildConversationFindIndex(messages, "  DePlOy  ");
    expect(index.matchCount).toBe(3);
    expect(index.matches.map((match) => match.messageId)).toEqual(["u1", "a1", "a1"]);
    expect(index.query).toBe("deploy");
  });

  it("records in-row ordinals and context snippets", () => {
    const messages = [
      assistantMessage("a1", [{ kind: "answer", id: "m1", text: "alpha beta alpha" }]),
    ];
    const index = buildConversationFindIndex(messages, "alpha");
    expect(index.matches.map((match) => match.matchIndexInRow)).toEqual([0, 1]);
    expect(index.matches[0]?.start).toBe(0);
    expect(index.matches[1]?.start).toBe(11);
    expect(index.matches[0]?.context).toBe("alpha beta alpha");
    expect(index.matches[0]?.context).not.toContain("…");
  });

  it("excludes in-flight assistant turns and admits them once settled", () => {
    const streaming = assistantMessage(
      "a1",
      [{ kind: "answer", id: "m1", text: "streaming needle" }],
      "running",
    );
    expect(collectConversationFindSegments(streaming)).toEqual([]);

    const settled = assistantMessage("a1", [{ kind: "answer", id: "m1", text: "streaming needle" }]);
    const index = buildConversationFindIndex([settled], "needle");
    expect(index.matchCount).toBe(1);
  });

  it("reuses cached matches for unchanged messages and rescans changed revisions only", () => {
    const cache = createConversationFindIndexCache();
    const messages = [
      userMessage("u1", "find the needle"),
      assistantMessage("a1", [
        { kind: "reasoning", id: "r1", text: "thinking about the needle" },
        { kind: "answer", id: "m1", text: "here is the needle" },
      ]),
    ];
    const scanned: Array<{ messageId: string; reused: boolean }> = [];
    const first = buildConversationFindIndex(messages, "needle", {
      cache,
      onMessageScan: (messageId, reused) => scanned.push({ messageId, reused }),
    });
    expect(first.matchCount).toBe(3);
    expect(scanned).toEqual([
      { messageId: "u1", reused: false },
      { messageId: "a1", reused: false },
    ]);

    // 流式更新：消息数组是新建的（slice），但未变化的消息命中缓存。
    scanned.length = 0;
    const second = buildConversationFindIndex([...messages], "needle", {
      cache,
      onMessageScan: (messageId, reused) => scanned.push({ messageId, reused }),
    });
    expect(second.matchCount).toBe(3);
    expect(scanned.every((entry) => entry.reused)).toBe(true);
    expect(second.matches).toEqual(first.matches);

    // assistant turnItem revision 变化 → 签名变化 → 只重扫该消息。
    // 修订后的正文不再含 needle：命中只剩 u1 + reasoning 两处。
    scanned.length = 0;
    const revisedMessages = [
      messages[0],
      assistantMessage("a1", [
        { kind: "reasoning", id: "r1", text: "thinking about the needle" },
        { kind: "answer", id: "m1", revision: 2, text: "the target moved here" },
      ]),
    ];
    const third = buildConversationFindIndex(revisedMessages, "needle", {
      cache,
      onMessageScan: (messageId, reused) => scanned.push({ messageId, reused }),
    });
    expect(third.matchCount).toBe(2);
    expect(scanned).toEqual([
      { messageId: "u1", reused: true },
      { messageId: "a1", reused: false },
    ]);
  });

  it("re-stamps messageOrder after prepend so cached matches never drift", () => {
    const cache = createConversationFindIndexCache();
    const later = [assistantMessage("a2", [{ kind: "answer", id: "m2", text: "needle two" }])];
    const first = buildConversationFindIndex(later, "needle", { cache });
    expect(first.matches[0]?.messageOrder).toBe(0);

    const withPrepend = [userMessage("u1", "needle one"), ...later];
    const second = buildConversationFindIndex(withPrepend, "needle", { cache });
    expect(second.matches.map((match) => [match.messageId, match.messageOrder])).toEqual([
      ["u1", 0],
      ["a2", 1],
    ]);
  });

  it("returns an empty index for blank queries without scanning", () => {
    const scanned: string[] = [];
    const index = buildConversationFindIndex([userMessage("u1", "anything")], "   ", {
      onMessageScan: (messageId) => scanned.push(messageId),
    });
    expect(index.matchCount).toBe(0);
    expect(index.matchedRowCount).toBe(0);
    expect(index.query).toBe("");
    expect(scanned).toEqual([]);
  });

  it("resolves the active index: -1 on zero matches, clamped on overflow", () => {
    expect(resolveConversationFindActiveIndex(0, 0)).toBe(-1);
    expect(resolveConversationFindActiveIndex(3, 1)).toBe(1);
    expect(resolveConversationFindActiveIndex(3, 9)).toBe(0);
    expect(resolveConversationFindActiveIndex(3, -1)).toBe(0);
  });

  it("wraps navigation: last → first, first → last, and keeps -1 on zero matches", () => {
    expect(stepConversationFindActiveIndex(2, 1, 3)).toBe(0);
    expect(stepConversationFindActiveIndex(0, -1, 3)).toBe(2);
    expect(stepConversationFindActiveIndex(-1, 1, 3)).toBe(0);
    expect(stepConversationFindActiveIndex(-1, -1, 3)).toBe(2);
    expect(stepConversationFindActiveIndex(-1, 1, 0)).toBe(-1);
    expect(stepConversationFindActiveIndex(0, 1, 0)).toBe(-1);
  });

  it("routes jumps: virtual rows through the virtualizer, live tail to the bottom", () => {
    expect(resolveConversationFindJumpPlan(2, 5)).toBe("virtual");
    expect(resolveConversationFindJumpPlan(5, 5)).toBe("liveTail");
    expect(resolveConversationFindJumpPlan(7, 5)).toBe("liveTail");
  });

  it("signatures stay stable across unchanged messages and change with revisions", () => {
    const message = assistantMessage("a1", [
      { kind: "answer", id: "m1", text: "unchanged text" },
    ]);
    expect(buildConversationFindMessageSignature(message))
      .toBe(buildConversationFindMessageSignature(assistantMessage("a1", [
        { kind: "answer", id: "m1", text: "rewritten text" },
      ])));
    expect(buildConversationFindMessageSignature(assistantMessage("a1", [
      { kind: "answer", id: "m1", revision: 2, text: "rewritten text" },
    ]))).not.toBe(buildConversationFindMessageSignature(message));
  });

  it("normalizes the query with trim and locale lower casing", () => {
    expect(normalizeConversationFindQuery("  ABC  ")).toBe("abc");
    expect(normalizeConversationFindQuery("")).toBe("");
  });
});
