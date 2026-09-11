import { afterEach, describe, expect, it, vi } from "vitest";

import type { AgentInstance, ConversationSummary, Team, TeamMember } from "../api/types";
import {
  agentDirectoryBucket,
  buildAgentDirectoryPartition,
  buildAgentDirectoryTeamRoomHistoryGroups,
  compareAgentDirectoryStableOrder,
  directoryTeamBlockIds,
  isConversationDirectoryAgent,
  isDirectoryTeamBlockTeam,
  isEligibleDirectoryAgent,
  readDirectoryCollapsedSections,
  writeDirectoryCollapsedSections,
} from "./agentConversationDirectoryModel";

afterEach(() => vi.unstubAllGlobals());

describe("directory display preferences", () => {
  it("remembers explicit expanded and collapsed sections", () => {
    const data = new Map<string, string>();
    vi.stubGlobal("localStorage", { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => data.set(key, value) });
    writeDirectoryCollapsedSections({ conversation: true, special: false, "team:research": false });
    expect(readDirectoryCollapsedSections()).toEqual({ conversation: true, special: false, "team:research": false });
  });

  it("matches the displayed model label without changing directory membership", () => {
    const partition = buildAgentDirectoryPartition({ agents: [agent({ displayName: "日常助手" })], teams: [], filterText: "Luna", resolveModelLabel: () => "Relay GPT-5.6 Luna" });
    expect(partition.conversationAgents.map((item) => item.agentId)).toEqual(["agent-1"]);
  });
});

function agent(overrides: Partial<AgentInstance> = {}): AgentInstance {
  return {
    agentId: "agent-1",
    agentCode: "A001",
    displayName: "会话 Agent",
    kind: "persistent",
    primaryMode: "chat",
    roleKey: "",
    llmBindings: { dialogue: { modelId: "model-primary" } },
    promptTemplateId: "prompt-chat-default",
    directSessionId: "",
    workspacePath: "workspace/agents/agent-1",
    toolPolicyId: "tool-agent-1",
    memoryPolicyId: "memory-agent-1",
    createdBy: "user",
    status: "active",
    metadata: { conversationIndexKind: "personal_agent" },
    createdAt: "2026-07-21T00:00:00Z",
    updatedAt: "2026-07-21T00:00:00Z",
    ...overrides,
  };
}

function member(overrides: Partial<TeamMember> = {}): TeamMember {
  return {
    memberId: "m1",
    agentId: "agent-team-1",
    agentCode: "T001",
    agentName: "资料员",
    role: "source_finder",
    purpose: "找资料",
    agentStatus: "active",
    ...overrides,
  };
}

function team(overrides: Partial<Team> = {}): Team {
  return {
    teamId: "team-1",
    name: "挑战杯团队",
    description: "",
    purpose: "科研",
    status: "active",
    teamKind: "research",
    teamCategory: "research",
    teamSource: "manual",
    members: [member()],
    memberCount: 1,
    linkedChatRoomId: "room-1",
    linkedChatRoom: {
      roomId: "room-1",
      title: "挑战杯群聊",
      status: "active",
      mode: "group",
      purpose: "team",
      participantCount: 2,
      updatedAt: "2026-07-30T00:00:00Z",
    },
    canvasPath: "",
    createdAt: "2026-07-01T00:00:00Z",
    updatedAt: "2026-07-30T00:00:00Z",
    canvas: { path: "", nodeCount: 0, edgeCount: 0 },
    ...overrides,
  };
}

describe("agentConversationDirectoryModel", () => {
  it("keeps Companion-owned Agents out of the ordinary chat directory", () => {
    const companion = agent({
      agentId: "agent-companion",
      metadata: {
        conversationIndexKind: "hidden",
        conversationIndexVisibility: "hidden",
        virtualHumanCompanion: true,
      },
    });

    expect(isEligibleDirectoryAgent(companion)).toBe(false);
    expect(buildAgentDirectoryPartition({ agents: [companion], teams: [] })).toEqual({
      conversationAgents: [],
      specialAgents: [],
      teamBlocks: [],
      listedAgentIds: [],
    });
  });
  it("classifies pure chat agents as conversation and role agents as special when unassigned", () => {
    const chat = agent();
    const observer = agent({
      agentId: "agent-observer",
      primaryMode: "self_evolution",
      roleKey: "observer",
      displayName: "观察员",
    });
    expect(isConversationDirectoryAgent(chat)).toBe(true);
    expect(isConversationDirectoryAgent(observer)).toBe(false);
    expect(agentDirectoryBucket(chat, new Set())).toBe("conversation");
    expect(agentDirectoryBucket(observer, new Set())).toBe("special");
    expect(agentDirectoryBucket(observer, new Set(["agent-observer"]))).toBe("team");
  });

  it("places unassigned archive-protected research-org chat agents under special", () => {
    const capabilityAdvisor = agent({
      agentId: "agent-capability-advisor",
      displayName: "能力顾问",
      primaryMode: "chat",
      roleKey: "",
      metadata: {
        conversationIndexKind: "personal_agent",
        researchOrgRole: "capability_steward",
      },
    });
    const organizationAdvisor = agent({
      agentId: "agent-org-advisor",
      displayName: "科研组织顾问",
      primaryMode: "chat",
      roleKey: "",
      metadata: {
        conversationIndexKind: "personal_agent",
        researchOrgRole: "organization_advisor",
      },
    });
    const assignedAdvisor = agent({
      agentId: "agent-assigned-advisor",
      displayName: "入队能力顾问",
      primaryMode: "chat",
      roleKey: "",
      metadata: {
        conversationIndexKind: "team_agent",
        researchOrgRole: "capability_steward",
      },
    });

    expect(isConversationDirectoryAgent(capabilityAdvisor)).toBe(false);
    expect(isConversationDirectoryAgent(organizationAdvisor)).toBe(false);
    expect(agentDirectoryBucket(capabilityAdvisor, new Set())).toBe("special");
    expect(agentDirectoryBucket(assignedAdvisor, new Set(["agent-assigned-advisor"]))).toBe("team");

    const partition = buildAgentDirectoryPartition({
      agents: [capabilityAdvisor, organizationAdvisor, assignedAdvisor, agent()],
      teams: [team({
        members: [member({
          memberId: "m-advisor",
          agentId: "agent-assigned-advisor",
          agentName: "入队能力顾问",
          role: "capability_steward",
        })],
      })],
    });

    expect(partition.conversationAgents.map((item) => item.agentId)).toEqual(["agent-1"]);
    expect(partition.specialAgents.map((item) => item.agentId).sort()).toEqual([
      "agent-capability-advisor",
      "agent-org-advisor",
    ]);
    expect(partition.teamBlocks[0]?.agents.map((item) => item.agentId)).toEqual(["agent-assigned-advisor"]);
  });

  it("places team members under their primary team and keeps special only for unassigned non-chat agents", () => {
    const chat = agent();
    const teamMemberAgent = agent({
      agentId: "agent-team-1",
      displayName: "资料员",
      primaryMode: "research",
      roleKey: "source_finder",
      conversationIndexKind: "team_agent",
      metadata: { conversationIndexKind: "team_agent" },
    });
    const orphanSpecial = agent({
      agentId: "agent-orphan",
      displayName: "全局观察",
      primaryMode: "self_evolution",
      roleKey: "observer",
    });
    const researchTeam = team();
    const partition = buildAgentDirectoryPartition({
      agents: [chat, teamMemberAgent, orphanSpecial],
      teams: [researchTeam],
    });

    expect(partition.conversationAgents.map((item) => item.agentId)).toEqual(["agent-1"]);
    expect(partition.specialAgents.map((item) => item.agentId)).toEqual(["agent-orphan"]);
    expect(partition.teamBlocks).toHaveLength(1);
    expect(partition.teamBlocks[0]?.team.teamId).toBe("team-1");
    expect(partition.teamBlocks[0]?.roomId).toBe("room-1");
    expect(partition.teamBlocks[0]?.agents.map((item) => item.agentId)).toEqual(["agent-team-1"]);
    expect(partition.listedAgentIds.sort()).toEqual(["agent-1", "agent-orphan", "agent-team-1"].sort());
  });

  it("assigns multi-team agents to the first primary team only", () => {
    const shared = agent({
      agentId: "agent-shared",
      displayName: "共享成员",
      primaryMode: "research",
      roleKey: "reviewer",
      conversationIndexKind: "team_agent",
      metadata: { conversationIndexKind: "team_agent" },
    });
    const teamA = team({
      teamId: "team-a",
      name: "团队 A",
      members: [member({ memberId: "ma", agentId: "agent-shared", agentName: "共享成员" })],
      memberCount: 1,
    });
    const teamB = team({
      teamId: "team-b",
      name: "团队 B",
      members: [member({ memberId: "mb", agentId: "agent-shared", agentName: "共享成员" })],
      memberCount: 1,
      linkedChatRoomId: "room-b",
      linkedChatRoom: {
        roomId: "room-b",
        title: "B 群",
        status: "active",
        mode: "group",
        purpose: "team",
        participantCount: 1,
        updatedAt: "2026-07-30T00:00:00Z",
      },
    });
    const partition = buildAgentDirectoryPartition({
      agents: [shared],
      teams: [teamA, teamB],
    });

    expect(partition.teamBlocks.map((block) => block.team.teamId)).toEqual(["team-a", "team-b"]);
    expect(partition.teamBlocks[0]?.agents.map((item) => item.agentId)).toEqual(["agent-shared"]);
    expect(partition.teamBlocks[1]?.agents).toEqual([]);
    expect(partition.specialAgents).toEqual([]);
  });

  it("hides empty special section content when every non-chat agent belongs to a team", () => {
    const teamMemberAgent = agent({
      agentId: "agent-team-1",
      displayName: "资料员",
      primaryMode: "research",
      roleKey: "source_finder",
      conversationIndexKind: "team_agent",
      metadata: { conversationIndexKind: "team_agent" },
    });
    const partition = buildAgentDirectoryPartition({
      agents: [teamMemberAgent],
      teams: [team()],
    });
    expect(partition.specialAgents).toEqual([]);
    expect(partition.conversationAgents).toEqual([]);
    expect(partition.teamBlocks[0]?.agents).toHaveLength(1);
  });

  it("places self-evolution and supervised-evolution teams under directory team blocks", () => {
    const observer = agent({
      agentId: "agent-self-obs",
      displayName: "自进化观察",
      primaryMode: "self_evolution",
      roleKey: "observer",
      conversationIndexKind: "team_agent",
      metadata: { conversationIndexKind: "team_agent" },
    });
    const evoTeam = team({
      teamId: "self-evolution-team",
      name: "自进化团队",
      teamKind: "self_evolution",
      teamSource: "self_evolution",
      members: [member({
        memberId: "m-obs",
        agentId: "agent-self-obs",
        agentName: "自进化观察",
        role: "observer",
      })],
      memberCount: 1,
      linkedChatRoomId: "room-self-evo",
      linkedChatRoom: {
        roomId: "room-self-evo",
        title: "自进化团队 团队群聊",
        status: "active",
        mode: "group",
        purpose: "team",
        participantCount: 1,
        updatedAt: "2026-07-30T00:00:00Z",
      },
    });
    const partition = buildAgentDirectoryPartition({
      agents: [observer],
      teams: [evoTeam],
    });
    expect(partition.teamBlocks.map((block) => block.team.teamId)).toEqual(["self-evolution-team"]);
    expect(partition.teamBlocks[0]?.roomId).toBe("room-self-evo");
    expect(partition.teamBlocks[0]?.agents.map((item) => item.agentId)).toEqual(["agent-self-obs"]);
    expect(partition.specialAgents).toEqual([]);
  });

  it("keeps conversation order by createdAt when a later rename bumps updatedAt", () => {
    const older = agent({
      agentId: "agent-older",
      displayName: "OpenCode Flash",
      createdAt: "2026-08-01T00:00:00Z",
      updatedAt: "2026-08-17T04:00:00Z",
    });
    const newer = agent({
      agentId: "agent-newer",
      displayName: "gpt-pix",
      createdAt: "2026-08-10T00:00:00Z",
      updatedAt: "2026-08-10T00:00:00Z",
    });
    const partition = buildAgentDirectoryPartition({
      agents: [older, newer],
      teams: [],
    });

    expect(compareAgentDirectoryStableOrder(older, newer)).toBeGreaterThan(0);
    expect(partition.conversationAgents.map((item) => item.agentId)).toEqual([
      "agent-newer",
      "agent-older",
    ]);
  });
});

function room(overrides: Partial<ConversationSummary> = {}): ConversationSummary {
  return {
    conversationId: "room-1",
    roomId: "room-1",
    type: "group_room",
    title: "SCI-009 | 候选评审 | sci-009-abc",
    status: "ready",
    summary: "",
    updatedAt: "2026-09-10T12:00:00Z",
    workspacePath: "",
    ...overrides,
  };
}

describe("buildAgentDirectoryTeamRoomHistoryGroups", () => {
  it("folds extra rooms by SCI topic with newest activity first and other last", () => {
    const groups = buildAgentDirectoryTeamRoomHistoryGroups([
      room({ roomId: "room-linked", title: "挑战杯ai科研团队 团队群聊", updatedAt: "2026-09-11T09:00:00Z" }),
      room({ roomId: "room-sci9-b", title: "SCI-009 | 候选生成 | sci-009-b", updatedAt: "2026-09-10T10:00:00Z" }),
      room({ roomId: "room-sci9-a", title: "SCI-009 | 候选评审 | sci-009-a", updatedAt: "2026-09-11T08:00:00Z" }),
      room({ roomId: "room-sci56", title: "SCI-056 | 候选评审 | sci-056-a", updatedAt: "2026-09-10T20:00:00Z" }),
      room({ roomId: "room-other", title: "手工房间", updatedAt: "2026-09-11T10:00:00Z" }),
    ], { linkedRoomId: "room-linked", otherLabel: "其他群聊" });

    expect(groups.map((group) => group.key)).toEqual(["SCI-009", "SCI-056", "__other__"]);
    expect(groups.map((group) => group.label)).toEqual(["SCI-009", "SCI-056", "其他群聊"]);
    expect(groups[0]?.items.map((item) => item.roomId)).toEqual(["room-sci9-a", "room-sci9-b"]);
    expect(groups[2]?.items.map((item) => item.roomId)).toEqual(["room-other"]);
    expect(groups.flatMap((group) => group.items).some((item) => item.roomId === "room-linked")).toBe(false);
  });

  it("falls back to conversationId when a room has no roomId and returns nothing for the linked-only case", () => {
    const legacyRoom = room({ conversationId: "legacy-1", roomId: "", title: "sci-012 候选生成" });
    const groups = buildAgentDirectoryTeamRoomHistoryGroups([legacyRoom], { otherLabel: "其他" });
    expect(groups).toHaveLength(1);
    expect(groups[0]?.key).toBe("SCI-012");
    expect(groups[0]?.items.map((item) => item.conversationId)).toEqual(["legacy-1"]);
    expect(buildAgentDirectoryTeamRoomHistoryGroups([room({ roomId: "room-linked" })], {
      linkedRoomId: "room-linked",
    })).toEqual([]);
  });
});

describe("directoryTeamBlockIds", () => {
  it("keeps only teams that render a directory block", () => {
    const memberTeam = team();
    const orphanTeam = team({
      teamId: "team-orphan",
      members: [],
      memberCount: 0,
      linkedChatRoomId: "",
      linkedChatRoom: {
        roomId: "",
        title: "",
        status: "active",
        mode: "group",
        purpose: "team",
        participantCount: 0,
        updatedAt: "",
      },
    });

    expect(isDirectoryTeamBlockTeam(memberTeam)).toBe(true);
    expect(isDirectoryTeamBlockTeam(orphanTeam)).toBe(false);
    expect([...directoryTeamBlockIds([memberTeam, orphanTeam])]).toEqual(["team-1"]);
  });
});
