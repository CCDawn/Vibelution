import { describe, expect, it } from "vitest";
import type { AssistantConversationTurn, ConversationMessage, SessionTurnItem } from "../../api/types/chat";
import { projectAgentMessageTimelineMessages } from "./useAgentMessageTimelineProjection";
import { conversationLiveTailStartIndex, guidanceDisplayState } from "./conversationGuidanceSegments";

const turnId = "session-guide-turn";
function item(id: string, sequence: number, synthetic = false): SessionTurnItem {
  return {
    version: 3, id, itemId: id, sessionId: "session-guide", turnId,
    type: "reasoning", text: id, status: "completed", revision: 1,
    sequence, terminal: true,
    metadata: { sequenceAuthority: synthetic ? "synthetic" : "journal" },
  };
}
function assistant(items: SessionTurnItem[], running = true): AssistantConversationTurn {
  return {
    id: running ? "session-guide-message-live-turn" : "session-guide-message-339",
    role: "assistant", turnId, status: running ? "running" : "completed",
    timestamp: "2026-10-22T05:29:41Z", turnItems: items,
    metadata: { kind: running ? "session_live_overlay" : "assistant_item_committed", turnId },
  };
}
function guide(id = "guide-1", sequence = 20, consumed = 30): ConversationMessage {
  return {
    id, role: "user", content: "请检查并行操作", timestamp: "2026-10-22T05:28:00Z",
    metadata: {
      kind: "user_guidance", turnId, guidanceEventId: id,
      guidanceSequence: sequence, guidanceConsumedSequence: consumed,
      guidanceState: consumed ? "drained" : "pending",
    },
  };
}
function layout(messages: ConversationMessage[]) {
  return projectAgentMessageTimelineMessages({ timelineMessages: messages });
}
function order(messages: ConversationMessage[]) {
  return messages.map((message) => message.role === "user"
    ? message.id : message.turnItems.map((entry) => entry.itemId).join(","));
}

describe("guidance work segments", () => {
  // 产品决策（2026-11-24）：插入消息固定渲染在本轮工作内容之后。
  // 一轮工作不再按 drained 的 consumed 序列切成多段；所有插入行都在 turn 尾部
  // 按 guidanceSequence 排序。下面每个用例都锁定这个单一形状。

  it("keeps the whole turn before the guide even after the drain receipt arrives", () => {
    const projected = layout([guide(), assistant([item("old-step", 10), item("finishing-tool", 25), item("new-step", 40)])]);
    expect(order(projected.messages)).toEqual(["old-step,finishing-tool,new-step", "guide-1"]);
    expect(projected.streamingMessages).toHaveLength(1);
  });

  it("keeps the same order after a fresh snapshot and final settlement", () => {
    const items = [item("old-step", 10), item("new-step", 40)];
    const live = layout([guide(), assistant(items)]);
    const refreshed = layout([assistant(items), guide()]);
    const settled = layout([assistant(items, false), guide()]);
    expect(order(live.messages)).toEqual(["old-step,new-step", "guide-1"]);
    expect(order(refreshed.messages)).toEqual(order(live.messages));
    expect(order(settled.messages)).toEqual(order(live.messages));
    expect(refreshed.rowIdentities.map((row) => row.rowKey)).toEqual(live.rowIdentities.map((row) => row.rowKey));
    expect(settled.rowIdentities.map((row) => row.rowKey)).toEqual(live.rowIdentities.map((row) => row.rowKey));
    expect(settled.streamingMessages).toHaveLength(0);
  });

  it("preserves repeated identical guidance as separate interventions", () => {
    const projected = layout([
      guide(), guide("guide-2", 45, 60),
      assistant([item("first", 10), item("second", 40), item("third", 70)]),
    ]);
    expect(order(projected.messages)).toEqual(["first,second,third", "guide-1", "guide-2"]);
    expect(new Set(projected.rowIdentities.map((row) => row.rowKey)).size).toBe(3);
  });

  it("keeps guide row identities when a refreshed message window changes positional ids", () => {
    const input = guide();
    const source = assistant([item("old", 10), item("new", 40)]);
    const before = layout([input, source]);
    const after = layout([{ ...input, id: "session-message-older-window-42" }, source]);
    expect(after.rowIdentities.map((row) => row.rowKey)).toEqual(before.rowIdentities.map((row) => row.rowKey));
  });

  it("shows waiting guidance after the current work without claiming that it was consumed", () => {
    const pending = guide("pending-guide", 20, 0);
    const projected = layout([pending, assistant([item("current-work", 10)])]);
    expect(order(projected.messages)).toEqual(["current-work", "pending-guide"]);
    expect(projected.messages.at(-1)?.metadata?.guidanceState).toBe("pending");
    expect(conversationLiveTailStartIndex(projected.messages)).toBe(0);
  });

  it("keeps synthetic work before the guide no matter when the drain receipt lands", () => {
    const old = item("live-reasoning", 1, true);
    old.metadata = { ...old.metadata, orderSequence: 10 };
    expect(order(layout([guide("guide-1", 20, 0), assistant([old])]).messages))
      .toEqual(["live-reasoning", "guide-1"]);
    expect(order(layout([guide(), assistant([old])]).messages))
      .toEqual(["live-reasoning", "guide-1"]);
    expect(order(layout([guide(), guide("guide-2", 45, 60), assistant([old], false)]).messages))
      .toEqual(["live-reasoning", "guide-1", "guide-2"]);
  });

  it("keeps new synthetic work inside its turn instead of splitting it out after the guide", () => {
    const current = item("new-reasoning", 1, true);
    current.metadata = { ...current.metadata, orderSequence: 40 };
    expect(order(layout([guide(), assistant([item("old-step", 10), current])]).messages))
      .toEqual(["old-step,new-reasoning", "guide-1"]);
  });

  it("does not move an existing item across a guide when a later revision updates it", () => {
    const revised = item("same-item", 40);
    revised.metadata = { ...revised.metadata, orderSequence: 10 };
    expect(order(layout([guide(), assistant([item("next-old-step", 15), revised], false)]).messages))
      .toEqual(["same-item,next-old-step", "guide-1"]);
  });

  it("never synthesizes an empty work segment after the guide", () => {
    const projected = layout([guide(), assistant([item("old-step", 10)])]);
    expect(order(projected.messages)).toEqual(["old-step", "guide-1"]);
    expect(projected.streamingMessages).toHaveLength(1);
  });

  it("keeps canonical action and usage ownership on the whole turn", () => {
    const source = assistant([item("old-step", 10), item("new-step", 40)], false);
    source.nodeId = "canonical-answer-node";
    source.usageStats = { inputTokens: 10, completionTokens: 5, totalTokens: 15, cachedInputTokens: 0 };
    const projected = layout([guide(), source]);
    expect(order(projected.messages)).toEqual(["old-step,new-step", "guide-1"]);
    const turn = projected.messages[0];
    expect(turn.role === "assistant" && turn.nodeId).toBe("canonical-answer-node");
    expect(turn.role === "assistant" && turn.usageStats).toBeDefined();
    expect(projected.messages.at(-1)?.id).toBe("guide-1");
  });

  it("leaves Companion projection and unrelated turns untouched", () => {
    const source = assistant([item("old-step", 10), item("new-step", 40)]);
    const other = guide();
    other.metadata = { ...other.metadata, turnId: "another-turn" };
    expect(layout([other, source]).messages.filter((message) => message.role === "assistant")).toHaveLength(1);
    const companion = projectAgentMessageTimelineMessages({ timelineMessages: [guide(), source], companionMode: true });
    expect(companion.messages.filter((message) => message.role === "assistant")).toHaveLength(1);
  });

  it("keeps the whole turn and its guides outside virtualized history", () => {
    const projected = layout([guide(), guide("waiting", 50, 0), assistant([item("old", 10), item("new", 40)])]);
    expect(order(projected.messages)).toEqual(["old,new", "guide-1", "waiting"]);
    expect(conversationLiveTailStartIndex(projected.messages)).toBe(0);
    expect(conversationLiveTailStartIndex([guide("orphan", 20, 0)])).toBe(1);
  });

  it("keeps unconfirmed guidance after work when the turn settles without consumption", () => {
    const historical = guide();
    historical.metadata = { ...historical.metadata, guidanceState: "unconfirmed", guidanceConsumedSequence: undefined };
    const projected = layout([assistant([item("old", 10), item("new", 40)], false), historical]);
    expect(order(projected.messages)).toEqual(["old,new", "guide-1"]);
    expect(guidanceDisplayState(historical)).toBe("received");
    const pending = guide("guide-1", 20, 0);
    expect(order(layout([assistant([item("old", 10), item("new", 40)]), pending]).messages))
      .toEqual(order(projected.messages));
  });

  it("retains failed-turn status and canonical actions if no new item arrived after the guide", () => {
    const source = assistant([item("last-real-work", 10)], false);
    source.status = "failed";
    source.nodeId = "failed-node";
    const projected = layout([source, guide()]);
    expect(order(projected.messages)).toEqual(["last-real-work", "guide-1"]);
    expect(projected.messages[0]).toMatchObject({ id: source.id, status: "failed", nodeId: "failed-node" });
  });
});
