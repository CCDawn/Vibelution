import { describe, expect, it } from "vitest";

import type { ConversationMessage, SessionDetail, SessionStreamEvent, SessionTurnItem } from "../api/types";
import * as chatActiveTurnLayerModule from "./chatActiveTurnLayer";
import {
  activeTurnLayerToConversationMessage,
  type ActiveTurnLayerState,
  activeTurnLayerTextLength,
  activeTurnTerminalRefreshKey,
  createOptimisticActiveTurnLayer,
  selectFirstUnpaintedRunningTool,
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
  it("selects each running tool once for first-paint telemetry", () => {
    const first = {
      id: "tool-a:1",
      itemId: "tool-a",
      version: 3,
      sessionId: "session-1",
      turnId: "turn-1",
      type: "tool_call",
      status: "running",
      revision: 1,
      sequence: 2,
      terminal: false,
      callId: "call-a",
      toolName: "glob_tool",
      createdAt: "2026-08-10T00:00:00Z",
      updatedAt: "2026-08-10T00:00:00Z",
    } satisfies SessionTurnItem;
    const second = {
      ...first,
      id: "tool-b:1",
      itemId: "tool-b",
      callId: "call-b",
      toolName: "grep_search_tool",
      sequence: 3,
    } satisfies SessionTurnItem;
    const layer = {
      id: "active",
      sessionId: "session-1",
      turnId: "turn-1",
      updatedAt: "2026-08-10T00:00:00Z",
      status: "running",
      turnItems: [first, second],
      ledgerSeq: 3,
    } satisfies ActiveTurnLayerState;

    expect(selectFirstUnpaintedRunningTool(layer, [])).toMatchObject({
      tool: { callId: "call-a" },
      runningToolIds: ["call-a", "call-b"],
    });
    expect(selectFirstUnpaintedRunningTool(layer, ["call-a"])).toMatchObject({
      tool: { callId: "call-b" },
    });
    expect(selectFirstUnpaintedRunningTool(layer, ["call-a", "call-b"]).tool).toBeUndefined();
  });

  it("requests one authoritative index refresh only for terminal active layers", () => {
    const layer = mergeAssistantDeltaIntoActiveTurnLayer(
      undefined,
      assistantDelta({ done: true, ledgerSeq: 9 }),
    );
    expect(activeTurnTerminalRefreshKey(layer)).toBe("turn-1:completed:9");
    expect(activeTurnTerminalRefreshKey({ ...layer!, status: "running" })).toBe("");
    expect(activeTurnTerminalRefreshKey(undefined)).toBe("");
  });

  it("keeps clientSubmissionId when an optimistic layer binds to a canonical turn", () => {
    const optimistic = createOptimisticActiveTurnLayer({
      sessionId: "session-1",
      turnId: "optimistic-submit",
      clientSubmissionId: "submission-1",
      updatedAt: "2026-08-10T00:00:00Z",
    });
    const bound = mergeAssistantDeltaIntoActiveTurnLayer(
      optimistic,
      assistantDelta({ turnId: "turn-accepted" }),
    );

    expect(bound?.clientSubmissionId).toBe("submission-1");
    expect(activeTurnLayerToConversationMessage(bound)?.metadata?.clientSubmissionId).toBe("submission-1");
  });

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
