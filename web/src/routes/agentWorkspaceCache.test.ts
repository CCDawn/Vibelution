import { describe, expect, it } from "vitest";

import type { AgentConfigWorkspace, AgentConfigWorkspaceAgent } from "../api/types";
import {
  archivedWorkspaceCache,
  bulkPurgeWorkspaceCache,
  purgedWorkspaceCache,
  updatedAgentWorkspaceCache,
  type AgentBulkActionResponse,
  type AgentConfigWorkspaceWithTeamIndexes,
} from "./agentWorkspaceCache";

function agent(agentId: string, overrides: Partial<AgentConfigWorkspaceAgent> = {}): AgentConfigWorkspaceAgent {
  return {
    agentId,
    agentCode: agentId,
    displayName: agentId,
    kind: "persistent",
    primaryMode: "chat",
    roleKey: "",
    llmBindings: {},
    promptTemplateId: "prompt-chat",
    directSessionId: `${agentId}-session`,
    workspacePath: `workspace/agents/${agentId}`,
    toolPolicyId: `tool-${agentId}`,
    memoryPolicyId: `memory-${agentId}`,
    createdBy: "test",
    status: "active",
    metadata: {},
    createdAt: "2026-06-01T00:00:00Z",
    updatedAt: "2026-06-01T00:00:00Z",
    references: [
      {
        kind: "direct_session",
        sourceId: `${agentId}-session`,
        sourceLabel: agentId,
        mode: "",
        field: "directSessionId",
        route: "/chat",
        status: "active",
      },
    ],
    health: [],
    agentBoundary: {
      type: "work_session",
      label: "会话工作 Agent",
      ownership: "user",
      directSessionRole: "primary_entry",
      reason: "work_session",
      configurationSurface: "work_session",
      requiresPersonaProfile: "false",
      requiresTaskProfile: "false",
      requiresTeamMembership: "false",
    },
    ...overrides,
  };
}

function workspace(): AgentConfigWorkspaceWithTeamIndexes {
  const alpha = agent("agent-alpha", {
    directSessionId: "alpha-session",
    references: [
      {
        kind: "direct_session",
        sourceId: "alpha-session",
        sourceLabel: "Alpha",
        mode: "",
        field: "directSessionId",
        route: "/chat",
        status: "active",
        sourceRef: {
          kind: "session",
          id: "alpha-session",
          owner: "ConversationLedger",
          factAuthority: true,
          canonicalEditRoute: "/chat?session=alpha-session",
          canonicalMutationApi: "/api/sessions/alpha-session",
          projectionCanWrite: false,
          allowedProjectionActions: ["view", "link", "refresh", "repair"],
          sourceAuthorityVersion: 1,
        },
        projectionEdit: {
          canWrite: false,
          mode: "deep_link_to_source",
          reason: "projection_read_model",
          sourceOwner: "ConversationLedger",
          canonicalEditRoute: "/chat?session=alpha-session",
          canonicalMutationApi: "/api/sessions/alpha-session",
          sourceAuthorityVersion: 1,
        },
        projectionCanWrite: false,
      },
      {
        kind: "mode_default",
        sourceId: "chat",
        sourceLabel: "chat default",
        mode: "chat",
        field: "",
        route: "",
        status: "active",
      },
      {
        kind: "chat_room",
        sourceId: "room-a",
        sourceLabel: "Room A",
        mode: "",
        field: "session-alpha",
        route: "/chat?room=room-a",
        status: "active",
      },
      {
        kind: "team",
        sourceId: "team-a",
        sourceLabel: "Team A",
        mode: "",
        field: "lead",
        route: "/teams?team=team-a",
        status: "active",
      },
    ],
    health: [
      {
        severity: "warning",
        code: "stale_chat_room_participant",
        agentId: "agent-alpha",
        title: "群聊成员引用了不可用 Agent",
        detail: "Room A",
        source: "chat_room",
        action: "fix",
      },
    ],
  });
  const beta = agent("agent-beta");
  return {
    schemaVersion: 1,
    generatedAt: "2026-06-01T00:00:00Z",
    storage: {
      agentRegistryPath: "workspace/agents/agents.json",
      modeBindingPath: "workspace/agent_config/mode_bindings.json",
      promptTemplatePath: "workspace/prompt_templates/prompt_templates.json",
    },
    summary: {
      agentCount: 2,
      activeAgentCount: 2,
      archivedAgentCount: 0,
      runningAgentCount: 0,
      blockedAgentCount: 0,
      modeCount: 1,
      chatRoomCount: 1,
      groupCount: 5,
      healthIssueCount: 1,
      blockingIssueCount: 0,
      warningIssueCount: 1,
      inboxPendingCount: 0,
      teamCount: 1,
    },
    groups: [
      { id: "active", label: "活跃 Agent", section: "status", agentIds: ["agent-alpha", "agent-beta"], count: 2, healthCount: 1 },
      { id: "archived", label: "已归档", section: "status", agentIds: [], count: 0, healthCount: 0 },
      { id: "chat", label: "会话模式", section: "mode", agentIds: ["agent-alpha", "agent-beta"], count: 2, healthCount: 1 },
      { id: "group_chat", label: "群聊引用", section: "reference", agentIds: ["agent-alpha"], count: 1, healthCount: 1 },
      { id: "team", label: "团队引用", section: "reference", agentIds: ["agent-alpha"], count: 1, healthCount: 1 },
    ],
    agents: [alpha, beta],
    modeBindings: {
      chat: {
        mode: "chat",
        defaultAgentId: "agent-alpha",
        availableAgentIds: ["agent-alpha", "agent-beta"],
        pool: ["agent-alpha"],
        flowBindings: { reviewer: "agent-alpha" },
        slots: { lead: "agent-alpha" },
        excludedAgentIds: ["agent-legacy"],
        excludedSlots: [],
        createdAt: "2026-06-01T00:00:00Z",
        updatedAt: "2026-06-01T00:00:00Z",
      },
    },
    promptTemplates: [],
    agentLlmSlots: [],
    agentModelChoices: [],
    modelOptions: [],
    toolPolicies: [],
    memoryPolicies: [],
    chatRooms: [
      {
        roomId: "room-a",
        title: "Room A",
        mode: "round_robin",
        status: "ready",
        activeRoundId: "",
        agentIds: ["agent-alpha", "agent-beta"],
        participantCount: 2,
        roundCount: 0,
        updatedAt: "2026-06-01T00:00:00Z",
      },
    ],
    teams: [
      {
        teamId: "team-a",
        name: "Team A",
        purpose: "",
        status: "active",
        agentIds: ["agent-alpha"],
        memberCount: 1,
        updatedAt: "2026-06-01T00:00:00Z",
      },
    ],
    references: {
      "agent-alpha": alpha.references,
      "agent-beta": beta.references,
    },
    health: {
      status: "warning",
      issues: alpha.health,
      counts: { blocking: 0, warning: 1, info: 0 },
      byAgent: { "agent-alpha": alpha.health },
    },
    repairWarnings: {
      modeBindings: [],
      promptTemplates: [],
    },
    teamIndexes: [
      {
        id: "team-a",
        label: "Team A",
        section: "team_index",
        agentIds: ["agent-alpha", "agent-beta"],
        count: 2,
        healthCount: 1,
        sourceScopeGroupId: "scope-a",
      },
    ],
  };
}

function archiveResponse(options: { removedFromTeamIds?: string[] } = {}): AgentConfigWorkspaceAgent & {
  archiveSummary: {
    removedFromRoomIds: string[];
    removedFromTeamIds: string[];
    dataRetention: string;
  };
} {
  return {
    ...workspace().agents[0],
    status: "archived",
    archiveSummary: {
      removedFromRoomIds: ["room-a"],
      removedFromTeamIds: options.removedFromTeamIds ?? [],
      dataRetention: "archived_only",
    },
  };
}

describe("agent workspace cache patching", () => {
  it("archives an Agent without leaving stale mode, room, and summary state", () => {
    const next = archivedWorkspaceCache(workspace(), archiveResponse({ removedFromTeamIds: ["team-a"] }));

    expect(next?.modeBindings.chat.defaultAgentId).toBe("agent-beta");
    expect(next?.modeBindings.chat.availableAgentIds).toEqual(["agent-beta"]);
    expect(next?.modeBindings.chat.pool).toEqual([]);
    expect(next?.modeBindings.chat.flowBindings).toEqual({});
    expect(next?.modeBindings.chat.slots.lead).toBe("");
    expect(next?.modeBindings.chat.excludedAgentIds).toEqual(["agent-legacy", "agent-alpha"]);
    expect(next?.chatRooms[0].agentIds).toEqual(["agent-beta"]);
    expect(next?.chatRooms[0].participantCount).toBe(1);
    expect(next?.health.status).toBe("ok");
    expect(next?.groups.find((group) => group.id === "active")?.agentIds).toEqual(["agent-beta"]);
    expect(next?.groups.find((group) => group.id === "archived")?.agentIds).toEqual(["agent-alpha"]);
    expect(next?.groups.find((group) => group.id === "team")?.agentIds).toEqual([]);
    expect(next?.teamIndexes?.[0].agentIds).toEqual(["agent-beta"]);
    expect(next?.summary).toMatchObject({
      agentCount: 2,
      activeAgentCount: 1,
      archivedAgentCount: 1,
      healthIssueCount: 0,
      warningIssueCount: 0,
    });
  });

  it("keeps unresolved team references visible as stale archive health", () => {
    const next = archivedWorkspaceCache(workspace(), archiveResponse());

    const alpha = next?.agents.find((item) => item.agentId === "agent-alpha");
    expect(alpha?.references.map((reference) => reference.kind)).toEqual(["direct_session", "team"]);
    expect(alpha?.references.find((reference) => reference.kind === "team")?.status).toBe("stale");
    expect(alpha?.health.map((issue) => issue.code)).toEqual(["stale_team_member"]);
    expect(next?.health.status).toBe("warning");
  });

  it("preserves source authority metadata when rebuilding archived direct-session references", () => {
    const next = archivedWorkspaceCache(workspace(), archiveResponse({ removedFromTeamIds: ["team-a"] }));

    const alpha = next?.agents.find((item) => item.agentId === "agent-alpha");
    const directSession = alpha?.references.find((reference) => reference.kind === "direct_session");

    expect(directSession?.sourceRef?.owner).toBe("ConversationLedger");
    expect(directSession?.sourceRef?.canonicalEditRoute).toBe("/chat?session=alpha-session");
    expect(directSession?.projectionEdit?.mode).toBe("deep_link_to_source");
    expect(directSession?.projectionCanWrite).toBe(false);
  });

  it("treats a PATCH status archive response like the archive mutation cache patch", () => {
    const next = updatedAgentWorkspaceCache(workspace(), archiveResponse({ removedFromTeamIds: ["team-a"] }));

    expect(next?.modeBindings.chat.availableAgentIds).toEqual(["agent-beta"]);
    expect(next?.chatRooms[0].agentIds).toEqual(["agent-beta"]);
    expect(next?.groups.find((group) => group.id === "active")?.agentIds).toEqual(["agent-beta"]);
    expect(next?.groups.find((group) => group.id === "archived")?.agentIds).toEqual(["agent-alpha"]);
    expect(next?.summary).toMatchObject({
      activeAgentCount: 1,
      archivedAgentCount: 1,
      healthIssueCount: 0,
    });
  });

  it("purges an Agent and keeps workspace counts and indexes aligned", () => {
    const next = purgedWorkspaceCache(workspace(), "agent-alpha");

    expect(next?.agents.map((item) => item.agentId)).toEqual(["agent-beta"]);
    expect(next?.references["agent-alpha"]).toBeUndefined();
    expect(next?.modeBindings.chat.availableAgentIds).toEqual(["agent-beta"]);
    expect(next?.modeBindings.chat.excludedAgentIds).toEqual(["agent-legacy"]);
    expect(next?.chatRooms[0].agentIds).toEqual(["agent-beta"]);
    expect(next?.teamIndexes?.[0].agentIds).toEqual(["agent-beta"]);
    expect(next?.summary).toMatchObject({
      agentCount: 1,
      activeAgentCount: 1,
      archivedAgentCount: 0,
      healthIssueCount: 0,
    });
  });

  it("applies bulk purge responses through the same single-Agent convergence path", () => {
    const response: AgentBulkActionResponse = {
      status: "ok",
      requestedAgentIds: ["agent-alpha"],
      success: [{ agentId: "agent-alpha", deleted: true, status: "purged" }],
      skipped: [],
      failed: [],
      summary: {
        requestedCount: 1,
        successCount: 1,
        skippedCount: 0,
        failedCount: 0,
      },
    };

    const next = bulkPurgeWorkspaceCache(workspace(), response);

    expect(next?.agents.map((item) => item.agentId)).toEqual(["agent-beta"]);
    expect(next?.modeBindings.chat.availableAgentIds).toEqual(["agent-beta"]);
    expect(next?.chatRooms[0].agentIds).toEqual(["agent-beta"]);
  });

  it("leaves unknown archive responses untouched instead of creating partial cache rows", () => {
    const original = workspace();
    const missing = agent("agent-missing", { status: "archived" });

    const next = archivedWorkspaceCache(original, missing);

    expect(next).toBe(original);
  });

  it("preserves undefined cache inputs", () => {
    expect(archivedWorkspaceCache(undefined, archiveResponse())).toBeUndefined();
    expect(purgedWorkspaceCache(undefined, "agent-alpha")).toBeUndefined();
  });

  it("is assignable to the base workspace contract", () => {
    const next: AgentConfigWorkspace | undefined = archivedWorkspaceCache(
      workspace(),
      archiveResponse({ removedFromTeamIds: ["team-a"] }),
    );

    expect(next?.schemaVersion).toBe(1);
  });
});
