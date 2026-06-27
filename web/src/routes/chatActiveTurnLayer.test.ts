import { describe, expect, it } from "vitest";

import type { ConversationMessage, SessionDetail, SessionStreamEvent } from "../api/types";
import {
  activeTurnLayerToConversationMessage,
  isActiveTurnSettledByDetail,
  mergeAssistantDeltaIntoActiveTurnLayer,
} from "./chatActiveTurnLayer";

function assistantDelta(
  patch: Partial<Extract<SessionStreamEvent, { type: "assistant_delta" }>>,
): Extract<SessionStreamEvent, { type: "assistant_delta" }> {
  return {
    type: "assistant_delta",
    sessionId: "session-1",
    turnId: "turn-1",
    ledgerSeq: 1,
    stage: "responding",
    content: "",
    thought: "",
    contentDelta: "",
    thoughtDelta: "",
    replaceContent: false,
    replaceThought: false,
    feedbackEvents: [],
    updatedAt: "2026-06-26T08:30:00Z",
    done: false,
    ...patch,
  };
}

describe("chat active turn layer", () => {
  it("merges assistant deltas into a separate active layer message", () => {
    const first = mergeAssistantDeltaIntoActiveTurnLayer(undefined, assistantDelta({ contentDelta: "你" }));
    const second = mergeAssistantDeltaIntoActiveTurnLayer(first, assistantDelta({ contentDelta: "好" }));

    expect(second?.content).toBe("你好");
    expect(second?.thought ?? "").toBe("");
    expect(second?.streaming).toBe(true);

    const message = activeTurnLayerToConversationMessage(second);

    expect(message?.id).toBe("session-1-message-active-turn-1");
    expect(message?.metadata?.kind).toBe("session_active_turn_layer");
    expect(message?.metadata?.turnId).toBe("turn-1");
    expect(message?.content).toBe("你好");
  });

  it("uses replace deltas as a full active-layer recovery snapshot", () => {
    const first = mergeAssistantDeltaIntoActiveTurnLayer(undefined, assistantDelta({ contentDelta: "旧内容" }));
    const recovered = mergeAssistantDeltaIntoActiveTurnLayer(
      first,
      assistantDelta({
        contentDelta: "完整内容",
        thoughtDelta: "完整思考",
        replaceContent: true,
        replaceThought: true,
      }),
    );

    expect(recovered?.content).toBe("完整内容");
    expect(recovered?.thought).toBe("完整思考");
  });

  it("updates the same unsequenced feedback event instead of appending a duplicate", () => {
    const first = mergeAssistantDeltaIntoActiveTurnLayer(
      undefined,
      assistantDelta({
        feedbackEvents: [
          {
            sequence: 0,
            kind: "tool",
            status: "running",
            name: "source_collection_context_tool",
            summary: "正在读取受控资料上下文",
          },
        ],
      }),
    );
    const updated = mergeAssistantDeltaIntoActiveTurnLayer(
      first,
      assistantDelta({
        feedbackEvents: [
          {
            sequence: 0,
            kind: "tool",
            status: "done",
            name: "source_collection_context_tool",
            summary: "上下文已读取",
            resultPreview: "candidatePage.returned=19",
          },
        ],
      }),
    );

    expect(updated?.feedbackEvents).toHaveLength(1);
    expect(updated?.feedbackEvents?.[0]).toMatchObject({
      kind: "tool",
      name: "source_collection_context_tool",
      status: "done",
      summary: "上下文已读取",
      resultPreview: "candidatePage.returned=19",
    });
  });

  it("keeps status-only assistant deltas out of answer content", () => {
    const active = mergeAssistantDeltaIntoActiveTurnLayer(
      undefined,
      assistantDelta({
        stage: "agent_prepare",
        content: "",
        contentDelta: "",
        feedbackEvents: [
          {
            sequence: 1,
            kind: "status",
            status: "running",
            name: "agent_prepare",
            summary: "正在唤起对话 agent",
          },
        ],
      }),
    );

    expect(active?.content).toBe("");
    expect(active?.streamStage).toBe("agent_prepare");
    expect(active?.feedbackEvents?.[0]).toMatchObject({
      kind: "status",
      name: "agent_prepare",
      status: "running",
    });
  });

  it("treats the active layer as settled once committed detail has the same assistant turn", () => {
    const active = mergeAssistantDeltaIntoActiveTurnLayer(undefined, assistantDelta({ contentDelta: "临时回答" }));
    const detail = {
      id: "session-1",
      messages: [
        {
          id: "assistant-final",
          role: "assistant",
          content: "正式回答",
          timestamp: "2026-06-26T08:31:00Z",
          metadata: { turnId: "turn-1" },
        } satisfies ConversationMessage,
      ],
    } as SessionDetail;

    expect(isActiveTurnSettledByDetail(active, detail)).toBe(true);
  });
});
