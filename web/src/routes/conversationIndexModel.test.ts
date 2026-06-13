import { describe, expect, it } from "vitest";

import type { ConversationSummary, SessionSummary, Team } from "../api/types";
import {
  buildConversationIndexModel,
  classifyConversation,
  conversationGroupLabel,
  hasInvalidChildSessionLink,
  isDiscussionTeam,
  mergeVisibleSessionsIntoConversations,
  rootSessionIdFor,
  sessionToConversationSummary,
} from "./conversationIndexModel";

function session(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id: "session-1",
    title: "用户会话",
    status: "idle",
    taskSummary: "摘要",
    lastActive: "2026-06-09T00:00:00.000Z",
    updatedAt: "2026-06-09T00:00:00.000Z",
    currentPhase: "idle",
    ...overrides,
  };
}

function conversation(overrides: Partial<ConversationSummary> = {}): ConversationSummary {
  return {
    conversationId: "session-1",
    directSessionId: "session-1",
    type: "direct_agent",
    title: "用户会话",
    status: "idle",
    summary: "摘要",
    updatedAt: "2026-06-09T00:00:00.000Z",
    workspacePath: "C:/workspace",
    ...overrides,
  };
}

function groupConversation(overrides: Partial<ConversationSummary> = {}): ConversationSummary {
  return conversation({
    conversationId: "room-1",
    directSessionId: "",
    roomId: "room-1",
    type: "group_room",
    title: "群聊",
    ...overrides,
  });
}

function team(overrides: Partial<Team> = {}): Team {
  return {
    teamId: "team-1",
    name: "研究团队",
    purpose: "证据审查",
    status: "active",
    members: [],
    memberCount: 1,
    linkedChatRoomId: "room-team",
    linkedChatRoom: { roomId: "room-team", title: "团队群聊", status: "idle" },
    teamKind: "research",
    teamCategory: "科研",
    teamSource: "",
    teamTemplateId: "",
    createdAt: "",
    updatedAt: "",
    ...overrides,
  };
}

describe("conversationIndexModel", () => {
  it("converts sessions to direct conversations without losing model and Agent metadata", () => {
    const summary = sessionToConversationSummary(session({
      agentCode: "A030",
      agentDisplayName: "顾明澈",
      dialogueModelId: "gpt-5.5",
      agentPrimaryMode: "chat",
      agentRoleKey: "knowledge",
      agentPromptTemplateId: "prompt-knowledge",
    }));

    expect(summary).toMatchObject({
      type: "direct_agent",
      title: "用户会话",
      agentCode: "A030",
      agentDisplayName: "顾明澈",
      dialogueModelId: "gpt-5.5",
      agentRoleKey: "knowledge",
    });
  });

  it("merges missing direct sessions from the session index and keeps newest conversations first", () => {
    const merged = mergeVisibleSessionsIntoConversations(
      [conversation({ conversationId: "old", directSessionId: "old", updatedAt: "2026-06-08T00:00:00.000Z" })],
      [session({ id: "new", title: "新会话", updatedAt: "2026-06-09T00:00:00.000Z" })],
    );

    expect(merged.map((item) => item.conversationId)).toEqual(["new", "old"]);
  });

  it("classifies and labels conversation groups", () => {
    expect(classifyConversation(conversation({ agentPrimaryMode: "research" }))).toBe("research");
    expect(classifyConversation(conversation({ title: "自进化 Agent" }))).toBe("selfEvolution");
    expect(conversationGroupLabel("research", "zh")).toBe("科研助手");
    expect(conversationGroupLabel("selfEvolution", "zh")).toBe("自进化助手");
    expect(conversationGroupLabel("supervisedEvolution", "zh")).toBe("监督进化助手");
    expect(conversationGroupLabel("other", "zh")).toBe("其他助手");
    expect(conversationGroupLabel("standaloneGroups", "zh")).toBe("未归属群聊");
  });

  it("derives the visible conversation index model with direct, team, and standalone filters", () => {
    const visibleSession = session({ id: "session-visible", title: "知识库管理" });
    const childSession = session({ id: "session-child", sessionKind: "child", parentSessionId: "session-visible" });
    const hiddenMissingSession = session({ id: "session-missing", agentMissing: true });
    const model = buildConversationIndexModel({
      conversations: [
        conversation({ directSessionId: "session-child", conversationId: "session-child" }),
        conversation({ directSessionId: "session-missing", conversationId: "session-missing", agentMissing: true }),
        groupConversation({ conversationId: "room-free", roomId: "room-free", title: "未绑定群" }),
        groupConversation({ conversationId: "room-team", roomId: "room-team", title: "团队群" }),
      ],
      lang: "zh",
      linkedTeamRoomIds: new Set(["room-team"]),
      rawSessions: [visibleSession, childSession, hiddenMissingSession],
      rightIndexSessions: [visibleSession],
      sessionFilter: "知识",
      sessionsById: new Map([[visibleSession.id, visibleSession], [childSession.id, childSession]]),
      teams: [
        team({ purpose: "知识治理" }),
        team({ teamId: "team-2", name: "普通团队", purpose: "闲聊" }),
        team({
          teamId: "self-evolution-team",
          name: "自进化团队",
          purpose: "自进化不需要讨论",
          teamKind: "self_evolution",
          teamSource: "self_evolution",
        }),
        team({
          teamId: "supervised-evolution-team",
          name: "监督进化团队",
          purpose: "监督进化不需要讨论",
          teamKind: "supervised_evolution",
          teamSource: "supervised_evolution",
        }),
      ],
    });

    expect(model.filteredConversations.map((item) => item.conversationId)).toEqual(["session-visible"]);
    expect(model.groupedConversations.map((group) => group.groupKey)).toEqual(["user"]);
    expect(model.filteredStandaloneGroupConversations).toEqual([]);
    expect(model.filteredTeams.map((item) => item.teamId)).toEqual(["team-1"]);
  });

  it("keeps non-discussion evolution system Teams out of the chat index", () => {
    expect(isDiscussionTeam(team({ teamId: "self-evolution-team" }))).toBe(false);
    expect(isDiscussionTeam(team({ teamKind: "supervised_evolution" }))).toBe(false);
    expect(isDiscussionTeam(team({ teamSource: "self_evolution" }))).toBe(false);
    expect(isDiscussionTeam(team({ teamKind: "research", teamSource: "research_organization" }))).toBe(true);
    expect(isDiscussionTeam(team({ teamKind: "ai_search", teamSource: "ai_search" }))).toBe(true);
  });

  it("tracks child-session root links for tab ownership", () => {
    const child = session({ sessionKind: "child", parentSessionId: "root-1" });
    const orphan = session({ sessionKind: "child", parentSessionId: "" });

    expect(rootSessionIdFor(child)).toBe("root-1");
    expect(hasInvalidChildSessionLink(orphan)).toBe(true);
  });
});
