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

  it("fills missing cached session avatar fields from the conversation index", () => {
    const cached = session({ id: "session-2", title: "用户改名", dialogueModelId: "gpt-5.5" });
    const result = conversationToSessionSummary(
      conversation({
        directSessionId: "session-2",
        title: "旧标题",
        agentAvatarImagePath: "workspace/avatars/01-session-agent.png",
        agentAvatarImageUrl: "/api/agents/avatar-image/01-session-agent.png",
      }),
      new Map([[cached.id, cached]]),
    );

    expect(result).not.toBe(cached);
    expect(result).toMatchObject({
      title: "用户改名",
      dialogueModelId: "gpt-5.5",
      agentAvatarImagePath: "workspace/avatars/01-session-agent.png",
      agentAvatarImageUrl: "/api/agents/avatar-image/01-session-agent.png",
    });
  });

  it("fills missing cached session source authority from the conversation index", () => {
    const cached = session({ id: "session-2", title: "用户改名", dialogueModelId: "gpt-5.5" });
    const result = conversationToSessionSummary(
      conversation({
        directSessionId: "session-2",
        sourceRef: {
          kind: "session",
          id: "session-2",
          owner: "ConversationLedger",
          factAuthority: true,
          canonicalEditRoute: "/chat?session=session-2",
          canonicalMutationApi: "/api/sessions/session-2",
          projectionCanWrite: false,
          allowedProjectionActions: ["view", "link", "refresh", "repair"],
          sourceAuthorityVersion: 1,
        },
        projectionEdit: {
          canWrite: false,
          mode: "deep_link_to_source",
          reason: "conversation_index_contract",
          sourceOwner: "ConversationLedger",
          canonicalEditRoute: "/chat?session=session-2",
          canonicalMutationApi: "/api/sessions/session-2",
          sourceAuthorityVersion: 1,
        },
        agentSourceRef: {
          kind: "agent",
          id: "agent-1",
          owner: "AgentDirectory",
          factAuthority: true,
          canonicalEditRoute: "/agents?agent=agent-1&pane=config",
          canonicalMutationApi: "/api/agents/agent-1",
          projectionCanWrite: false,
          allowedProjectionActions: ["view", "link", "refresh", "repair"],
          sourceAuthorityVersion: 1,
        },
        conversationIndexVisibility: "team_private",
        conversationIndexKind: "team_agent",
        conversationIndexErrors: ["missing_source_authority"],
      }),
      new Map([[cached.id, cached]]),
    );

    expect(result).not.toBe(cached);
    expect(result.title).toBe("用户改名");
    expect(result.dialogueModelId).toBe("gpt-5.5");
    expect(result.sourceRef?.owner).toBe("ConversationLedger");
    expect(result.projectionEdit?.mode).toBe("deep_link_to_source");
    expect(result.agentSourceRef?.canonicalEditRoute).toBe("/agents?agent=agent-1&pane=config");
    expect(result.conversationIndexVisibility).toBe("team_private");
    expect(result.conversationIndexKind).toBe("team_agent");
    expect(result.conversationIndexErrors).toEqual(["missing_source_authority"]);
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

  it("preserves source authority metadata in the fallback session summary", () => {
    const result = conversationToSessionSummary(
      conversation({
        directSessionId: "session-3",
        sourceRef: {
          kind: "session",
          id: "session-3",
          owner: "ConversationLedger",
          factAuthority: true,
          canonicalEditRoute: "/chat?session=session-3",
          canonicalMutationApi: "/api/sessions/session-3",
          projectionCanWrite: false,
          allowedProjectionActions: ["view", "link", "refresh", "repair"],
          sourceAuthorityVersion: 1,
        },
        projectionEdit: {
          canWrite: false,
          mode: "deep_link_to_source",
          reason: "conversation_index_contract",
          sourceOwner: "ConversationLedger",
          canonicalEditRoute: "/chat?session=session-3",
          canonicalMutationApi: "/api/sessions/session-3",
          sourceAuthorityVersion: 1,
        },
        agentSourceRef: {
          kind: "agent",
          id: "agent-1",
          owner: "AgentDirectory",
          factAuthority: true,
          canonicalEditRoute: "/agents?agent=agent-1&pane=config",
          canonicalMutationApi: "/api/agents/agent-1",
          projectionCanWrite: false,
          allowedProjectionActions: ["view", "link", "refresh", "repair"],
          sourceAuthorityVersion: 1,
        },
        conversationIndexVisibility: "team_private",
        conversationIndexKind: "team_agent",
        conversationIndexErrors: ["missing_source_authority"],
      }),
      new Map(),
    );

    expect(result.sourceRef?.owner).toBe("ConversationLedger");
    expect(result.projectionEdit?.reason).toBe("conversation_index_contract");
    expect(result.agentSourceRef?.canonicalEditRoute).toBe("/agents?agent=agent-1&pane=config");
    expect(result.conversationIndexVisibility).toBe("team_private");
    expect(result.conversationIndexKind).toBe("team_agent");
    expect(result.conversationIndexErrors).toEqual(["missing_source_authority"]);
  });
});
