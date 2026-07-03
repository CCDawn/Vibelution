import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { conversationMessageToAgentMessage } from "../../agent-thread";
import { buildAgentMessageRenderState } from "./agentMessageRenderState";

function message(overrides: Partial<ConversationMessage>): ConversationMessage {
  return {
    id: "msg",
    role: "assistant",
    content: "最终回答",
    timestamp: "2026-07-03T11:05:00Z",
    ...overrides,
  };
}

describe("agentMessageRenderState", () => {
  it("collects AgentMessage section ids and typed section groups for rendering", () => {
    const agentMessage = conversationMessageToAgentMessage(
      message({
        id: "assistant-render-state",
        feedbackEvents: [
          {
            sequence: 1,
            kind: "tool",
            status: "done",
            name: "read_file_tool",
            summary: "读取 ConversationView",
          },
        ],
        references: [
          {
            kind: "session",
            sessionId: "session-ref",
            title: "历史会话",
          },
        ],
      }),
    );

    const renderState = buildAgentMessageRenderState(agentMessage);

    expect(renderState.sectionState.sectionKinds).toEqual(["process", "content", "context"]);
    expect(renderState.sectionKinds).toBe("process content context");
    expect(renderState.userContentSectionIds).toBeUndefined();
    expect(renderState.answerContentSectionIds).toBe("assistant-render-state-section-content-1");
    expect(renderState.processSectionIds).toBe("assistant-render-state-section-process-0");
    expect(renderState.processSections.map((section) => section.id)).toEqual([
      "assistant-render-state-section-process-0",
    ]);
    expect(renderState.contextSections.map((section) => section.id)).toEqual([
      "assistant-render-state-section-context-2",
    ]);
  });

  it("derives process signals, tool calls, and text length from the AgentMessage model", () => {
    const agentMessage = conversationMessageToAgentMessage(
      message({
        id: "assistant-legacy-render-state",
        content: "最终回答",
        thought: "旧链路思考",
        toolCalls: [
          {
            name: "legacy_tool",
            status: "running",
            summary: "正在执行旧工具",
            resultPreview: "result preview",
          },
        ],
        mentalSnapshot: {
          mood: "steady",
          feeling: "谨慎",
          whisper: "继续收敛",
          summary: "心智摘要",
          cognitiveState: "focused",
          confidence: 0.88,
          sampleSize: 2,
          interventionCount: 1,
          updatedAt: "2026-07-03T11:04:00Z",
          source: "runtime",
        },
      }),
    );

    const renderState = buildAgentMessageRenderState(agentMessage);

    expect(renderState.renderedTextLength).toBe("最终回答".length + "旧链路思考".length);
    expect(renderState.toolCalls.map((toolCall) => toolCall.name)).toEqual(["legacy_tool"]);
    expect(renderState.processSignal).toContain("legacy_tool");
    expect(renderState.processSignal).toContain("running");
    expect(renderState.processSignal).toContain("心智摘要");
    expect(renderState.processSignalWithoutMental).toContain("legacy_tool");
    expect(renderState.processSignalWithoutMental).not.toContain("心智摘要");
  });
});
