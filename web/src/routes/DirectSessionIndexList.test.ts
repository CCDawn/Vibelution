import { describe, expect, it } from "vitest";

import type { ConversationSummary, SessionSummary } from "../api/types";
import { conversationToSessionSummary } from "./DirectSessionIndexList";

function conversation(overrides: Partial<ConversationSummary> = {}): ConversationSummary {
  return {
    conversationId: "conversation-1",
    type: "direct_agent",
    title: "会话标题",
    status: "idle",
    summary: "摘要",
    updatedAt: "2026-06-09T00:00:00.000Z",
    workspacePath: "C:/workspace",
    ...overrides,
  };
}

function session(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id: "session-1",
    title: "已有会话",
    status: "idle",
    taskSummary: "已有摘要",
    lastActive: "2026-06-09T00:00:00.000Z",
    updatedAt: "2026-06-09T00:00:00.000Z",
    currentPhase: "idle",
    ...overrides,
  };
}

describe("DirectSessionIndexList helpers", () => {
  it("prefers the cached session summary when it has already been loaded", () => {
    const cached = session({ id: "session-2", title: "用户改名", dialogueModelId: "gpt-5.5" });
    const result = conversationToSessionSummary(
      conversation({ directSessionId: "session-2", title: "旧标题" }),
      new Map([[cached.id, cached]]),
    );

    expect(result).toBe(cached);
    expect(result.title).toBe("用户改名");
  });

  it("preserves direct conversation metadata in the fallback session summary", () => {
    const result = conversationToSessionSummary(
      conversation({
        directSessionId: "session-3",
        agentId: "agent-1",
        agentCode: "A030",
        agentDisplayName: "顾明澈",
        agentPrimaryMode: "chat",
        agentRoleKey: "knowledge",
        agentPromptTemplateId: "prompt-knowledge",
        dialogueModelId: "gpt-5.5",
        agentMissing: true,
        agentStatusCode: "missing",
        agentStatusMessage: "Agent 已删除",
      }),
      new Map(),
    );

    expect(result).toMatchObject({
      id: "session-3",
      title: "会话标题",
      agentId: "agent-1",
      agentCode: "A030",
      agentDisplayName: "顾明澈",
      agentPrimaryMode: "chat",
      agentRoleKey: "knowledge",
      agentPromptTemplateId: "prompt-knowledge",
      dialogueModelId: "gpt-5.5",
      agentMissing: true,
      agentStatusCode: "missing",
      agentStatusMessage: "Agent 已删除",
      taskSummary: "摘要",
      currentPhase: "idle",
    });
  });
});
