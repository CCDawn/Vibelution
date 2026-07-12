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
  });

  it("merges assistant deltas into a separate active layer message", () => {
    const first = mergeAssistantDeltaIntoActiveTurnLayer(undefined, assistantDelta({ contentDelta: "你" }));
    const second = mergeAssistantDeltaIntoActiveTurnLayer(first, assistantDelta({ contentDelta: "好" }));

    expect(second?.answerContent).toBe("你好");
    expect(second?.thoughtContent ?? "").toBe("");
    expect(second?.streaming).toBe(true);

    const message = activeTurnLayerToConversationMessage(second);

    expect(message?.id).toBe("session-1-message-active-turn-1");
    expect(message?.metadata?.kind).toBe("session_active_turn_layer");
    expect(message?.metadata?.turnId).toBe("turn-1");
    expect(message?.content).toBe("你好");
  });

  it("creates an optimistic assistant layer as soon as the user submits content", () => {
    const active = createOptimisticActiveTurnLayer({
      sessionId: "session-1",
      turnId: "optimistic-submit",
      updatedAt: "2026-07-10T01:10:00Z",
    });

    const message = activeTurnLayerToConversationMessage(active);

    expect(active).toMatchObject<Partial<ActiveTurnLayerState>>({
      id: "session-1-message-active-optimistic-submit",
      sessionId: "session-1",
      turnId: "optimistic-submit",
      streaming: true,
      processStage: "user_submit",
      answerContent: "",
      thoughtContent: "",
      ledgerSeq: 0,
    });
    expect(active?.feedbackEvents).toEqual([
      {
        sequence: 1,
        kind: "status",
        status: "running",
        name: "user_submit",
        summary: "已发送，正在连接 Agent",
      },
    ]);
    expect(message).toMatchObject<Partial<ConversationMessage>>({
      role: "assistant",
      streaming: true,
      streamStage: "user_submit",
      content: "",
      metadata: {
        kind: "session_active_turn_layer",
        sessionId: "session-1",
        turnId: "optimistic-submit",
        ledgerSeq: 0,
      },
    });
    expect(message?.feedbackEvents?.[0]).toMatchObject({
      kind: "status",
      status: "running",
      name: "user_submit",
    });
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

    expect(recovered?.answerContent).toBe("完整内容");
    expect(recovered?.thoughtContent).toBe("完整思考");
  });

  it("preserves native Codex transcript snapshots across assistant deltas", () => {
    const first = mergeAssistantDeltaIntoActiveTurnLayer(
      undefined,
      assistantDelta({
        contentDelta: "",
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "session-1-message-live-turn-1",
          cells: [
            {
              id: "native-tool",
              kind: "tool_call",
              messageId: "session-1-message-live-turn-1",
              status: "running",
              tone: "running",
              title: "npm build",
            },
          ],
        },
      }),
    );
    const second = mergeAssistantDeltaIntoActiveTurnLayer(
      first,
      assistantDelta({
        contentDelta: "最终回答",
        feedbackEvents: undefined,
      }),
    );

    expect(second?.codexTranscript?.cells[0]).toMatchObject({
      id: "native-tool",
      kind: "tool_call",
    });

    const message = activeTurnLayerToConversationMessage(second);

    expect(message?.content).toBe("最终回答");
    expect(message?.codexTranscript?.source).toBe("native");
    expect(message?.codexTranscript?.cells[0]?.id).toBe("native-tool");
  });

  it("keeps internal native assistant markdown snapshots out of the visible active layer", () => {
    const statusText = "context_prepare\n正在准备对话上下文...\n\nmodel_request\n正在请求模型，等待首个响应片段...\n\nretrying\n模型连接正在重试...\n第 1/5 次；原因：server_error。本轮仍在继续，请不要重复提交。";
    const active = mergeAssistantDeltaIntoActiveTurnLayer(
      undefined,
      assistantDelta({
        stage: "model_request",
        contentDelta: "",
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "session-1-message-live-turn-1",
          cells: [
            {
              id: "native-status-markdown",
              kind: "assistant_markdown",
              messageId: "session-1-message-live-turn-1",
              status: "completed",
              tone: "neutral",
              text: statusText,
            },
          ],
        },
      }),
    );

    expect(active).toBeUndefined();
  });

  it("keeps native assistant markdown answer visible when legacy content is empty", () => {
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
              id: "native-answer",
              kind: "assistant_markdown",
              messageId: "session-1-message-live-turn-1",
              status: "completed",
              tone: "neutral",
              text: "这是 native transcript 里的最终回答。",
            },
          ],
        },
      }),
    );

    const message = activeTurnLayerToConversationMessage(active);

    expect(active).toBeDefined();
    expect(activeTurnLayerTextLength(active)).toBeGreaterThan(0);
    expect(message?.content).toBe("");
    expect(message?.codexTranscript?.source).toBe("native");
    expect(message?.codexTranscript?.cells[0]).toMatchObject({
      id: "native-answer",
      kind: "assistant_markdown",
      text: "这是 native transcript 里的最终回答。",
    });
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

  it("keeps internal status-only assistant deltas out of the visible active layer", () => {
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

    expect(active).toBeUndefined();
  });

  it("keeps diagnostic status-only assistant deltas in the visible active layer", () => {
    const active = mergeAssistantDeltaIntoActiveTurnLayer(
      undefined,
      assistantDelta({
        stage: "model_failed",
        content: "",
        contentDelta: "",
        feedbackEvents: [
          {
            sequence: 1,
            kind: "status",
            status: "failed",
            name: "model_failed",
            summary: "模型请求失败。",
            error: "provider upstream unavailable",
          },
        ],
      }),
    );

    const message = activeTurnLayerToConversationMessage(active);

    expect(message?.content).toBe("");
    expect(message?.streamStage).toBe("model_failed");
    expect(message?.feedbackEvents?.[0]).toMatchObject({
      kind: "status",
      name: "model_failed",
      status: "failed",
    });
  });

  it("drops internal status text from assistant delta answer content", () => {
    const active = mergeAssistantDeltaIntoActiveTurnLayer(
      undefined,
      assistantDelta({
        stage: "agent_prepare",
        content: "正在唤起对话 agent...\n正在绑定 Agent 实例、私人工作区、记忆根和工具工作区。",
        contentDelta: undefined,
        feedbackEvents: [
          {
            sequence: 1,
            kind: "status",
            status: "running",
            name: "agent_prepare",
            summary: "正在绑定 Agent",
          },
        ],
      }),
    );

    expect(active).toBeUndefined();
  });

  it("keeps answer text visible without retaining internal status feedback", () => {
    const preparing = mergeAssistantDeltaIntoActiveTurnLayer(
      undefined,
      assistantDelta({
        stage: "agent_prepare",
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
    expect(preparing).toBeUndefined();

    const responding = mergeAssistantDeltaIntoActiveTurnLayer(
      preparing,
      assistantDelta({
        stage: "responding",
        contentDelta: "真正回答",
        feedbackEvents: [
          {
            sequence: 2,
            kind: "status",
            status: "running",
            name: "model_request",
            summary: "正在请求模型",
          },
        ],
      }),
    );

    expect(responding).toMatchObject<Partial<ActiveTurnLayerState>>({
      answerContent: "真正回答",
      thoughtContent: "",
      processStage: "responding",
      streaming: true,
    });
    expect(responding?.feedbackEvents?.map((event) => event.name)).toEqual([]);
    const message = activeTurnLayerToConversationMessage(responding);

    expect(message?.content).toBe("真正回答");
    expect(message?.metadata?.kind).toBe("session_active_turn_layer");
    expect(message?.feedbackEvents).toBeUndefined();
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

  it("does not settle the active layer for a process-only same-turn assistant packet", () => {
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
  });

  it("settles the active layer for a same-turn terminal canonical error", () => {
    const active = mergeAssistantDeltaIntoActiveTurnLayer(undefined, assistantDelta({ contentDelta: "临时回答" }));
    const detail = {
      id: "session-1",
      messages: [
        {
          id: "assistant-error",
          role: "assistant",
          content: "",
          timestamp: "2026-07-13T00:00:00.000Z",
          metadata: { turnId: "turn-1" },
          turnItems: [
            {
              version: 2,
              id: "error:0",
              itemId: "error",
              type: "error",
              kind: "error",
              status: "failed",
              terminal: true,
              provisional: false,
              text: "上游服务暂不可用。",
            },
          ],
        } satisfies ConversationMessage,
      ],
    } as SessionDetail;

    expect(isActiveTurnSettledByDetail(active, detail)).toBe(true);
  });

  it("settles the active layer when committed detail has same-turn native assistant markdown answer", () => {
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
          id: "assistant-final-native",
          role: "assistant",
          content: "",
          timestamp: "2026-06-26T08:31:00Z",
          codexTranscript: {
            version: 1,
            source: "native",
            messageId: "assistant-final-native",
            cells: [
              {
                id: "native-final-answer",
                kind: "assistant_markdown",
                messageId: "assistant-final-native",
                status: "completed",
                tone: "neutral",
                text: "正式 native 回答。",
              },
            ],
          },
          metadata: { turnId: "turn-1" },
        } satisfies ConversationMessage,
      ],
    } as SessionDetail;

    expect(isActiveTurnSettledByDetail(active, detail)).toBe(true);
  });

  it("does not settle the active layer for same-turn native process-only transcript", () => {
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

describe("canonical SessionTurnItem v2 active turn", () => {
  it("replaces the same item revision across streamed payloads without duplicating the answer", () => {
    const common = {
      type: "assistant_delta",
      sessionId: "session-v2",
      turnId: "turn-v2",
      content: "legacy duplicate",
      replaceContent: true,
      updatedAt: "2026-07-11T00:00:00.000Z",
    } as const;
    const item = (revision: number, text: string, terminal: boolean) => ({
      version: 2,
      id: `answer-r${revision}`,
      itemId: "answer",
      sessionId: "session-v2",
      turnId: "turn-v2",
      invocationId: "invocation-v2",
      iteration: 0,
      revision,
      sequence: revision + 1,
      kind: "assistant_message",
      channel: "answer",
      phase: "final_answer",
      type: "assistant_message",
      status: terminal ? "completed" : "running",
      provisional: !terminal,
      terminal,
      text,
    });
    const draft = canonicalActiveTurn.mergeAssistantDeltaIntoActiveTurnLayer(undefined, {
      ...common,
      ledgerSeq: 1,
      done: false,
      turnItems: [item(0, "draft", false)],
    } as never);
    const final = canonicalActiveTurn.mergeAssistantDeltaIntoActiveTurnLayer(draft, {
      ...common,
      ledgerSeq: 2,
      done: true,
      turnItems: [item(1, "final", true)],
    } as never);
    const message = canonicalActiveTurn.activeTurnLayerToConversationMessage(final);

    expect(message?.content).toBe("final");
    expect(message?.turnItems).toHaveLength(1);
    expect(message?.codexTranscript?.cells.filter((cell) => cell.kind === "assistant_markdown")).toHaveLength(1);
  });
});
