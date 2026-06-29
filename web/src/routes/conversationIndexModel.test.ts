import { describe, expect, it } from "vitest";

import type { AgentInstance, ConversationSummary, SessionSummary, Team } from "../api/types";
import {
  agentToConversationSummary,
  buildConversationIndexModel,
  classifyConversation,
  conversationGroupLabel,
  DEFAULT_COLLAPSED_CONVERSATION_GROUPS,
  hasInvalidChildSessionLink,
  isDiscussionTeam,
  isVisibleConversationAgent,
  normalizeConversationIndexTeams,
  mergeVisibleAgentsIntoConversations,
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
    conversationIndexKind: "user_chat",
    conversationIndexErrors: [],
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
    conversationIndexKind: "user_chat",
    conversationIndexErrors: [],
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

function agent(overrides: Partial<AgentInstance> = {}): AgentInstance {
  return {
    agentId: "agent-1",
    agentCode: "A001",
    displayName: "科研助手",
    kind: "persistent",
    primaryMode: "research",
    roleKey: "research_quality",
    llmBindings: { dialogue: { modelId: "mimo-v2.5" } },
    promptTemplateId: "prompt-research-quality",
    directSessionId: "session-agent-1",
    workspacePath: "C:/workspace/agent-1",
    toolPolicyId: "default",
    memoryPolicyId: "default",
    createdBy: "user",
    conversationIndexVisibility: "user_visible",
    conversationIndexKind: "personal_agent",
    conversationIndexErrors: [],
    status: "idle",
    metadata: {},
    createdAt: "2026-06-09T00:00:00.000Z",
    updatedAt: "2026-06-09T00:00:00.000Z",
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
      agentInboxPendingCount: 4,
    }));

    expect(summary).toMatchObject({
      type: "direct_agent",
      title: "用户会话",
      agentCode: "A030",
      agentDisplayName: "顾明澈",
      dialogueModelId: "gpt-5.5",
      agentRoleKey: "knowledge",
      agentInboxPendingCount: 4,
      sourceRef: {
        owner: "ConversationLedger",
        canonicalEditRoute: "/chat?session=session-1",
        projectionCanWrite: false,
      },
      projectionEdit: {
        canWrite: false,
        mode: "deep_link_to_source",
      },
    });
  });

  it("preserves backend source authority refs when converting sessions", () => {
    const summary = sessionToConversationSummary(session({
      id: "session-source",
      sourceRef: {
        kind: "session",
        id: "session-source",
        owner: "ConversationLedger",
        factAuthority: true,
        canonicalEditRoute: "/chat?session=session-source",
        canonicalMutationApi: "/api/sessions/session-source",
        projectionCanWrite: false,
        allowedProjectionActions: ["view", "link"],
        sourceAuthorityVersion: 1,
      },
      agentSourceRef: {
        kind: "agent",
        id: "agent-source",
        owner: "AgentDirectory",
        factAuthority: true,
        canonicalEditRoute: "/agents?agent=agent-source&pane=config",
        canonicalMutationApi: "/api/agents/agent-source",
        projectionCanWrite: false,
        allowedProjectionActions: ["view", "link"],
        sourceAuthorityVersion: 1,
      },
    }));

    expect(summary.sourceRef?.canonicalEditRoute).toBe("/chat?session=session-source");
    expect(summary.agentSourceRef?.canonicalEditRoute).toBe("/agents?agent=agent-source&pane=config");
    expect(summary.projectionEdit?.canWrite).toBe(false);
  });

  it("merges missing direct sessions from the session index and keeps newest conversations first", () => {
    const merged = mergeVisibleSessionsIntoConversations(
      [conversation({ conversationId: "old", directSessionId: "old", updatedAt: "2026-06-08T00:00:00.000Z" })],
      [session({ id: "new", title: "新会话", updatedAt: "2026-06-09T00:00:00.000Z" })],
    );

    expect(merged.map((item) => item.conversationId)).toEqual(["new", "old"]);
  });

  it("hydrates existing direct conversations from the session index before classification", () => {
    const merged = mergeVisibleSessionsIntoConversations(
      [
        conversation({
          conversationId: "session-direct",
          directSessionId: "session-direct",
          title: "唐映白",
          conversationIndexKind: undefined,
          conversationIndexErrors: undefined,
        }),
      ],
      [
        session({
          id: "session-direct",
          title: "唐映白",
          conversationIndexKind: "personal_agent",
          conversationIndexVisibility: "user_visible",
          conversationIndexErrors: [],
        }),
      ],
    );

    expect(merged).toHaveLength(1);
    expect(merged[0]).toMatchObject({
      conversationId: "session-direct",
      directSessionId: "session-direct",
      conversationIndexKind: "personal_agent",
      conversationIndexVisibility: "user_visible",
      conversationIndexErrors: [],
    });
    expect(classifyConversation(merged[0])).toBe("personalAgent");
  });

  it("converts visible persistent Agents into direct conversations for the categorized chat index", () => {
    const summary = agentToConversationSummary(agent({
      agentId: "agent-research",
      agentCode: "R001",
      displayName: "证据审查",
      directSessionId: "session-research",
      agentInboxPendingCount: 2,
    }));

    expect(summary).toMatchObject({
      conversationId: "session-research",
      directSessionId: "session-research",
      type: "direct_agent",
      title: "证据审查",
      agentId: "agent-research",
      agentPrimaryMode: "research",
      agentRoleKey: "research_quality",
      agentPromptTemplateId: "prompt-research-quality",
      dialogueModelId: "mimo-v2.5",
      agentInboxPendingCount: 2,
      sourceRef: {
        owner: "AgentDirectory",
        canonicalEditRoute: "/agents?agent=agent-research&pane=config",
        projectionCanWrite: false,
      },
      agentSourceRef: {
        owner: "AgentDirectory",
        canonicalEditRoute: "/agents?agent=agent-research&pane=config",
      },
      projectionEdit: {
        canWrite: false,
        mode: "deep_link_to_source",
      },
    });
  });

  it("only adds clickable, non-archived persistent Agents that are not already represented by sessions", () => {
    const existing = conversation({ conversationId: "session-existing", directSessionId: "session-existing", agentId: "agent-existing" });
    const merged = mergeVisibleAgentsIntoConversations(
      [existing],
      [
        agent({ agentId: "agent-existing", directSessionId: "session-existing", displayName: "已有会话" }),
        agent({ agentId: "agent-missing", directSessionId: "session-missing", displayName: "缺席分页 Agent" }),
        agent({
          agentId: "agent-team-private",
          directSessionId: "session-team-private",
          displayName: "挑战杯资料发现",
          createdBy: "challenge_cup_team",
          conversationIndexKind: "hidden",
          metadata: { challengeCupTeamId: "research-team" },
        }),
        agent({ agentId: "agent-archived", directSessionId: "session-archived", status: "archived" }),
        agent({ agentId: "agent-no-session", directSessionId: "" }),
      ],
    );

    expect(isVisibleConversationAgent(agent({ status: "archived" }))).toBe(false);
    expect(isVisibleConversationAgent(agent({ directSessionId: "" }))).toBe(false);
    expect(isVisibleConversationAgent(agent({ conversationIndexKind: "hidden" }))).toBe(false);
    expect(isVisibleConversationAgent(agent({ conversationIndexVisibility: "team_private" }))).toBe(true);
    expect(
      isVisibleConversationAgent(agent({
        createdBy: "challenge_cup_team",
        conversationIndexKind: undefined,
        conversationIndexVisibility: undefined,
        metadata: { challengeCupTeamId: "research-team" },
      })),
    ).toBe(true);
    expect(
      isVisibleConversationAgent(agent({
        conversationIndexKind: undefined,
        conversationIndexVisibility: undefined,
        roleKey: "source_finder",
        metadata: {},
      })),
    ).toBe(true);
    expect(merged.map((item) => item.conversationId).sort()).toEqual(["session-existing", "session-missing"]);
  });

  it("does not let an Agent placeholder overwrite a conversation with the same direct session id", () => {
    const existing = conversation({
      conversationId: "agent-shared-direct",
      directSessionId: "agent-shared-direct",
      agentId: "agent-original",
      title: "资料入库",
    });

    const merged = mergeVisibleAgentsIntoConversations(
      [existing],
      [
        agent({
          agentId: "agent-other",
          directSessionId: "agent-shared-direct",
          displayName: "唐望舒",
        }),
      ],
    );

    expect(merged).toHaveLength(1);
    expect(merged[0]).toMatchObject({
      directSessionId: "agent-shared-direct",
      agentId: "agent-original",
      title: "资料入库",
    });
  });

  it("classifies and labels conversation groups", () => {
    expect(classifyConversation(conversation({ conversationIndexKind: "user_chat", agentPrimaryMode: "research" }))).toBe("user");
    expect(classifyConversation(conversation({ conversationIndexKind: "personal_agent", title: "自进化 Agent" }))).toBe("personalAgent");
    expect(classifyConversation(conversation({ conversationIndexKind: "team_agent" }))).toBe("invalid");
    expect(classifyConversation(conversation({ conversationIndexKind: "invalid" }))).toBe("invalid");
    expect(conversationGroupLabel("user", "zh")).toBe("用户会话");
    expect(conversationGroupLabel("personalAgent", "zh")).toBe("个人 Agent 会话");
    expect(conversationGroupLabel("invalid", "zh")).toBe("异常会话");
    expect(conversationGroupLabel("other", "zh")).toBe("其他助手");
    expect(conversationGroupLabel("setupTeams", "zh")).toBe("待配置团队");
    expect(conversationGroupLabel("standaloneGroups", "zh")).toBe("未归属群聊");
    expect(DEFAULT_COLLAPSED_CONVERSATION_GROUPS.user).toBe(false);
    expect(DEFAULT_COLLAPSED_CONVERSATION_GROUPS.personalAgent).toBe(false);
    expect(DEFAULT_COLLAPSED_CONVERSATION_GROUPS.invalid).toBe(false);
    expect(DEFAULT_COLLAPSED_CONVERSATION_GROUPS.other).toBe(false);
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
      agents: [],
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

  it("groups visible Agents by category even when their sessions are not in the current session page", () => {
    const model = buildConversationIndexModel({
      agents: [
        agent({ agentId: "agent-research-1", directSessionId: "session-research-1", displayName: "许景行", primaryMode: "research" }),
        agent({ agentId: "agent-research-2", directSessionId: "session-research-2", displayName: "白书遥", primaryMode: "research" }),
        agent({
          agentId: "agent-user",
          directSessionId: "session-user",
          displayName: "周书遥",
          primaryMode: "chat",
          roleKey: "chat",
          promptTemplateId: "prompt-chat",
        }),
      ],
      conversations: [],
      lang: "zh",
      linkedTeamRoomIds: new Set(),
      rawSessions: [],
      rightIndexSessions: [],
      sessionFilter: "",
      sessionsById: new Map(),
      teams: [],
    });

    const groups = new Map(model.groupedConversations.map((group) => [group.groupKey, group.items]));
    expect(groups.get("personalAgent")?.map((item) => item.title)).toEqual(expect.arrayContaining(["白书遥", "周书遥", "许景行"]));
    expect(groups.get("personalAgent")).toHaveLength(3);
    expect(model.filteredConversations.map((item) => item.directSessionId).sort()).toEqual([
      "session-research-1",
      "session-research-2",
      "session-user",
    ]);
  });

  it("puts repaired direct Agents without an explicit index kind into the invalid group", () => {
    const model = buildConversationIndexModel({
      agents: [
        agent({
          agentId: "agent-repaired",
          directSessionId: "session-repaired",
          displayName: "周南栀",
          primaryMode: "chat",
          roleKey: "",
          promptTemplateId: "prompt-chat",
          createdBy: "session_repair",
          conversationIndexKind: undefined,
          conversationIndexVisibility: undefined,
          metadata: { directSessionVisibility: "active_session", functionalDisplayName: "真实会话" },
        }),
      ],
      conversations: [],
      lang: "zh",
      linkedTeamRoomIds: new Set(),
      rawSessions: [],
      rightIndexSessions: [],
      sessionFilter: "",
      sessionsById: new Map(),
      teams: [],
    });

    expect(model.groupedConversations.map((group) => group.groupKey)).toEqual(["invalid"]);
    expect(model.groupedConversations[0].items[0]).toMatchObject({
      conversationId: "session-repaired",
      title: "周南栀",
      conversationIndexKind: "invalid",
      conversationIndexErrors: expect.arrayContaining([
        "missing_conversation_index_kind",
        "session_repair_missing_conversation_index_kind",
      ]),
    });
  });

  it("deduplicates same-name empty Teams before they reach the chat index", () => {
    const teams = normalizeConversationIndexTeams([
      team({ teamId: "team", name: "挑战杯科研团队", memberCount: 0, members: [], linkedChatRoomId: "room-team" }),
      team({ teamId: "team-2", name: "挑战杯科研团队", memberCount: 0, members: [], linkedChatRoomId: "room-team-2" }),
      team({ teamId: "research-team", name: "挑战杯ai科研团队", teamSource: "research_organization", memberCount: 4 }),
    ]);

    expect(teams.map((item) => item.teamId)).toEqual(["team", "research-team"]);
    expect(teams[0].conversationIndexDuplicateCount).toBe(2);
    expect(teams[0].conversationIndexHiddenTeamIds).toEqual(["team-2"]);
    expect(teams[0].conversationIndexSetupReason).toBe("empty_members");
    expect(teams[1].conversationIndexSetupReason).toBeUndefined();
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
