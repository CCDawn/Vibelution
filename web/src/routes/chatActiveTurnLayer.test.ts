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
  runningToolStartedAtEpochMs,
  runningToolPaintKeys,
  toolStartToFirstPaintMs,
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
      toolIds: ["call-a", "call-b"],
      runningToolIds: ["call-a", "call-b"],
    });
    expect(selectFirstUnpaintedRunningTool(layer, ["call-a"])).toMatchObject({
      tool: { callId: "call-b" },
      toolIds: ["call-b"],
    });
    expect(selectFirstUnpaintedRunningTool(layer, ["call-a", "call-b"]).tool).toBeUndefined();
  });

  it("measures tool paint from the running revision instead of model call creation", () => {
    const runningTool = {
      id: "tool-a:2",
      itemId: "tool-a",
      version: 3,
      sessionId: "session-1",
      turnId: "turn-1",
      type: "tool_call",
      status: "running",
      revision: 2,
      sequence: 2,
      terminal: false,
      callId: "call-a",
      toolName: "glob_tool",
      createdAt: "2026-08-10T00:00:00.000Z",
      updatedAt: "2026-08-10T00:00:01.250Z",
      metadata: { executionStartedAtEpochMs: 1_786_294_801_125 },
    } satisfies SessionTurnItem;

    expect(runningToolStartedAtEpochMs(runningTool)).toBe(1_786_294_801_125);
    expect(runningToolStartedAtEpochMs({ ...runningTool, metadata: {} })).toBe(
      Date.parse("2026-08-10T00:00:01.250Z"),
    );
  });

  it("does not consume first-paint telemetry before a start timestamp arrives", () => {
    const placeholder = {
      id: "tool-a:0",
      itemId: "tool-a",
      version: 3,
      sessionId: "session-1",
      turnId: "turn-1",
      type: "tool_call",
      status: "running",
      revision: 0,
      sequence: 2,
      terminal: false,
      callId: "call-a",
      toolName: "glob_tool",
    } satisfies SessionTurnItem;
    const layer = {
      id: "active",
      sessionId: "session-1",
      turnId: "turn-1",
      updatedAt: "2026-08-10T00:00:00Z",
      status: "running",
      turnItems: [placeholder],
      ledgerSeq: 2,
    } satisfies ActiveTurnLayerState;

    expect(selectFirstUnpaintedRunningTool(layer, [])).toMatchObject({
      tool: undefined,
      toolIds: [],
      runningToolIds: ["call-a"],
    });
    expect(selectFirstUnpaintedRunningTool({
      ...layer,
      turnItems: [{
        ...placeholder,
        revision: 1,
        metadata: { executionStartedAtEpochMs: 1_786_294_801_125 },
      }],
    }, [])).toMatchObject({
      tool: { callId: "call-a" },
      toolIds: ["call-a"],
    });
  });

  it("measures from the placeholder row's first paint when exact start arrives later", () => {
    const tool = {
      id: "tool-late:1",
      itemId: "tool-late",
      version: 3,
      sessionId: "session-1",
      turnId: "turn-1",
      type: "tool_call",
      status: "running",
      revision: 1,
      sequence: 2,
      callId: "call-late",
      toolName: "grep_search_tool",
      metadata: { executionStartedAtEpochMs: 1_000 },
    } satisfies SessionTurnItem;

    expect(toolStartToFirstPaintMs(tool, 1_055, 6_000)).toBe(55);
    expect(toolStartToFirstPaintMs(tool, 999, 6_000)).toBe(1);
  });

  it("keeps a bounded name-occurrence fallback when a placeholder call id changes", () => {
    const base = {
      id: "tool-a:1",
      itemId: "tool-a",
      version: 3,
      sessionId: "session-1",
      turnId: "turn-1",
      type: "tool_call",
      status: "completed",
      revision: 1,
      sequence: 1,
      callId: "call-a",
      toolName: "grep_search_tool",
    } satisfies SessionTurnItem;
    const layer = {
      id: "active",
      sessionId: "session-1",
      turnId: "turn-1",
      updatedAt: "2026-08-10T00:00:00Z",
      status: "running",
      turnItems: [base, {
        ...base,
        id: "tool-placeholder:1",
        itemId: "tool-placeholder",
        callId: "placeholder-id",
        status: "running",
        sequence: 2,
      }],
      ledgerSeq: 2,
    } satisfies ActiveTurnLayerState;

    expect(runningToolPaintKeys(layer)).toEqual([{
      toolId: "placeholder-id",
      fallbackKey: "tool:grep_search_tool:1",
    }]);

    const regressedFirstTool = {
      ...base,
      id: "tool-a-exact:2",
      itemId: "tool-a-exact",
      callId: "call-a-exact",
      status: "running" as const,
      revision: 2,
      metadata: { executionStartedAtEpochMs: 1_786_294_801_125 },
    };
    const secondTool = {
      ...base,
      id: "tool-b:1",
      itemId: "tool-b",
      callId: "call-b",
      toolName: "grep_search_tool",
      status: "running" as const,
      sequence: 2,
      metadata: { executionStartedAtEpochMs: 1_786_294_806_000 },
    };
    const regressedLayer = {
      ...layer,
      turnItems: [regressedFirstTool, secondTool],
    } satisfies ActiveTurnLayerState;

    expect(selectFirstUnpaintedRunningTool(
      regressedLayer,
      ["placeholder-call-id", "tool:grep_search_tool:0"],
    )).toMatchObject({
      toolId: "call-b",
      toolIds: ["call-b"],
    });
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

  it("requests an authoritative index refresh when persisted detail settles a still-running layer", () => {
    const layer = mergeAssistantDeltaIntoActiveTurnLayer(
      undefined,
      assistantDelta({ done: false, ledgerSeq: 8 }),
    );
    const detail = {
      id: "session-1",
      ledgerSeq: 10,
      messages: [{
        id: "assistant-final",
        role: "assistant",
        status: "completed",
        turnId: "turn-1",
        timestamp: "2026-08-10T00:00:01Z",
        turnItems: [{
          id: "answer:1",
          itemId: "answer",
          version: 3,
          sessionId: "session-1",
          turnId: "turn-1",
          type: "final_answer",
          status: "completed",
          revision: 1,
          sequence: 10,
          terminal: true,
          text: "DONE",
          createdAt: "2026-08-10T00:00:01Z",
          updatedAt: "2026-08-10T00:00:01Z",
        }],
      }],
    } as SessionDetail;

    expect(activeTurnTerminalRefreshKey(layer, detail)).toBe("turn-1:detail:10");
    expect(activeTurnTerminalRefreshKey({ ...layer!, status: "completed" }, detail)).toBe("turn-1:detail:10");
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
