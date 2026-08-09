import { describe, expect, it } from "vitest";

import type { ConversationMessage, SessionDetail, SessionStreamEvent } from "../api/types";
import * as chatActiveTurnLayerModule from "./chatActiveTurnLayer";
import {
  activeTurnLayerToConversationMessage,
  type ActiveTurnLayerState,
  activeTurnLayerTextLength,
  createOptimisticActiveTurnLayer,
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
  it("keeps AgentMessage projection behind the shared conversation adapter", () => {
    expect("activeTurnLayerToAgentMessage" in chatActiveTurnLayerModule).toBe(false);
  });it("does not settle the active layer for a process-only same-turn assistant packet", () => {
    const active = mergeAssistantDeltaIntoActiveTurnLayer(undefined, assistantDelta({ contentDelta: "临时回答" }));
    const detail = {
      id: "session-1",
      messages: [
        {
          id: "assistant-process",
          role: "assistant",
          content: "",
          timestamp: "2026-06-26T08:31:00Z",
          feedbackEvents: [
            {
              sequence: 1,
              kind: "status",
              status: "running",
              name: "model_request",
              summary: "正在请求模型",
            },
          ],
          metadata: { turnId: "turn-1" },
        } satisfies ConversationMessage,
      ],
    } as SessionDetail;

    expect(isActiveTurnSettledByDetail(active, detail)).toBe(false);
  });  it("does not settle the active layer for same-turn native process-only transcript", () => {
    const active = mergeAssistantDeltaIntoActiveTurnLayer(
      undefined,
      assistantDelta({
        contentDelta: "",
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "session-1-message-live-turn-1",
          cells: [
            {
              id: "native-live-answer",
              kind: "assistant_markdown",
              messageId: "session-1-message-live-turn-1",
              status: "completed",
              tone: "neutral",
              text: "流式阶段的 native 回答。",
            },
          ],
        },
      }),
    );
    const detail = {
      id: "session-1",
      messages: [
        {
          id: "assistant-final-tool",
          role: "assistant",
          content: "",
          timestamp: "2026-06-26T08:31:00Z",
          codexTranscript: {
            version: 1,
            source: "native",
            messageId: "assistant-final-tool",
            cells: [
              {
                id: "native-tool",
                kind: "tool_call",
                messageId: "assistant-final-tool",
                status: "completed",
                tone: "neutral",
                title: "npm build",
                summary: "构建完成",
              },
            ],
          },
          metadata: { turnId: "turn-1" },
        } satisfies ConversationMessage,
      ],
    } as SessionDetail;

    expect(isActiveTurnSettledByDetail(active, detail)).toBe(false);
  });
});
import * as canonicalActiveTurn from "./chatActiveTurnLayer";