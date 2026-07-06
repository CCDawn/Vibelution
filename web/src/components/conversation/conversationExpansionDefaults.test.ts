import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import type { AgentMessageRenderState } from "./agentMessageRenderState";
import type { AgentMessageTimelineItem } from "./agentMessageTimeline";
import type { AgentMessageOperation, AgentMessageOperationGroups } from "./agentMessageOperations";
import { preserveConversationExpansionDefaults } from "./conversationExpansionDefaults";

function renderState(hasResponseBlock: boolean): AgentMessageRenderState {
  return {
    processSections: [],
    contextSections: [],
    toolCalls: [],
    renderedTextLength: 0,
    answerContentSectionIds: undefined,
    processSectionIds: undefined,
    sectionState: {
      answerText: hasResponseBlock ? "回答内容" : "",
      userText: "",
      hasFeedbackTimeline: true,
      hasResponseBlock,
      hasUserContent: false,
    },
  };
}

function operation(overrides: Partial<AgentMessageOperation> = {}): AgentMessageOperation {
  return {
    id: overrides.id ?? "operation-1",
    kind: overrides.kind ?? "tool",
    label: overrides.label ?? "命令",
    status: overrides.status ?? "running",
    summary: overrides.summary ?? "正在执行",
    durationSeconds: null,
    ...overrides,
  };
}

function operationGroups(operations: AgentMessageOperation[]): AgentMessageOperationGroups {
  return {
    timeline: operations,
    thoughts: operations.filter((item) => item.kind === "thought"),
    mental: operations.filter((item) => item.kind === "mental"),
    status: operations.filter((item) => item.kind === "status"),
    tools: operations.filter((item) => item.kind === "tool"),
  };
}

describe("conversation expansion defaults", () => {
  it("preserves process and timeline defaults before top-edge history loading changes the visible window", () => {
    const runningMessage: ConversationMessage = {
      id: "message-running",
      role: "assistant",
      content: "实时回答",
      timestamp: "2026-07-06T11:00:00Z",
      streaming: true,
    };
    const completedMessage: ConversationMessage = {
      id: "message-completed",
      role: "assistant",
      content: "历史回答",
      timestamp: "2026-07-06T10:59:00Z",
    };
    const runningTimelineItems: AgentMessageTimelineItem[] = [
      {
        id: "message-running-thought",
        kind: "thought",
        status: "running",
        text: "正在分析",
        preview: "正在分析",
        defaultExpanded: true,
        sourceOperationIds: ["thought-1"],
      },
      {
        id: "message-running-command-group",
        kind: "command_group",
        status: "running",
        title: "正在运行 2 条命令",
        summary: "搜索；读取",
        operations: [operation({ id: "tool-1" }), operation({ id: "tool-2" })],
      },
    ];

    const defaults = preserveConversationExpansionDefaults({
      currentDefaults: {
        "message-running": {
          response: false,
        },
      },
      sectionExpansion: {
        "message-running": {
          feedback: true,
        },
      },
      messages: [completedMessage, runningMessage],
      renderStatesByMessageId: new Map([
        [runningMessage.id, renderState(true)],
        [completedMessage.id, renderState(true)],
      ]),
      timelineItemsByMessageId: new Map([
        [runningMessage.id, runningTimelineItems],
      ]),
      operationGroupsByMessageId: new Map([
        [runningMessage.id, operationGroups([operation({ id: "running-tool", status: "running" })])],
        [completedMessage.id, operationGroups([operation({ id: "completed-tool", status: "done" })])],
      ]),
      defaultExpandedResponseIds: new Set([runningMessage.id]),
    });

    expect(defaults["message-running"].response).toBe(false);
    expect(defaults["message-running"].process).toBe(true);
    expect(defaults["message-running"].feedback).toBeUndefined();
    expect(defaults["message-running"]["message-running-thought"]).toBe(true);
    expect(defaults["message-running"]["message-running-command-group"]).toBe(false);
    expect(defaults["message-completed"].response).toBe(false);
    expect(defaults["message-completed"].process).toBe(false);
    expect(defaults["message-completed"].feedback).toBe(false);
  });

  it("preserves failed ReAct feedback expansion defaults during history loading", () => {
    const failedMessage: ConversationMessage = {
      id: "message-failed",
      role: "assistant",
      content: "失败后继续分析",
      timestamp: "2026-07-06T11:10:00Z",
    };

    const defaults = preserveConversationExpansionDefaults({
      currentDefaults: {},
      sectionExpansion: {},
      messages: [failedMessage],
      renderStatesByMessageId: new Map([
        [failedMessage.id, renderState(true)],
      ]),
      timelineItemsByMessageId: new Map(),
      operationGroupsByMessageId: new Map([
        [failedMessage.id, operationGroups([
          operation({ id: "thought-1", kind: "thought", status: "done", sequence: 1, resultPreview: "先尝试搜索" }),
          operation({
            id: "tool-1",
            kind: "tool",
            status: "failed",
            sequence: 2,
            relatedThoughtSequence: 1,
            error: "timeout",
          }),
        ])],
      ]),
      defaultExpandedResponseIds: new Set(),
    });

    expect(defaults["message-failed"].process).toBe(false);
    expect(defaults["message-failed"].feedback).toBe(true);
  });
});
