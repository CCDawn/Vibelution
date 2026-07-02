import type {
  AgentBoundary,
  AgentConfigHealthIssue,
  AgentConfigReference,
  AgentConfigWorkspace,
  AgentConfigWorkspaceAgent,
  AgentConfigWorkspaceGroup,
  AgentModeBindingItem,
} from "../api/types";

export type AgentTeamIndexGroup = AgentConfigWorkspaceGroup & {
  section: "team_index" | "source_scope";
  agentIds: string[];
  teamId?: string;
  teamKind?: string;
  teamCategory?: string;
  sourceScopeGroupId?: string;
  sourceCount?: number;
  enabledByDefault?: boolean;
  evidenceRole?: string;
  source?: string;
};

export type AgentConfigWorkspaceWithTeamIndexes = AgentConfigWorkspace & {
  teamIndexes?: AgentTeamIndexGroup[];
};

export type AgentArchiveResponse = AgentConfigWorkspaceAgent & {
  archiveSummary?: {
    modeBindingsRepaired?: number;
    removedFromRoomIds?: string[];
    removedFromTeamIds?: string[];
    dataRetention?: string;
    source?: string;
  };
};

export type AgentBulkActionItem = {
  agentId: string;
  reason?: string;
  message?: string;
  status?: string;
  deleted?: boolean;
  archiveSummary?: Record<string, unknown>;
  purgeSummary?: Record<string, unknown>;
};

export type AgentBulkActionResponse = {
  status: string;
  requestedAgentIds: string[];
  success: AgentBulkActionItem[];
  skipped: AgentBulkActionItem[];
  failed: AgentBulkActionItem[];
  summary: {
    requestedCount: number;
    successCount: number;
    skippedCount: number;
    failedCount: number;
  };
  cleanupSummary?: Record<string, unknown>;
  timingsMs?: Record<string, number>;
  durationMs?: number;
};

const ARCHIVED_BOUNDARY: AgentBoundary = {
  type: "archived",
  label: "已归档 Agent",
  ownership: "archive",
  directSessionRole: "historical_recovery",
  reason: "agent_archived",
  configurationSurface: "archive",
  requiresPersonaProfile: "false",
  requiresTaskProfile: "false",
  requiresTeamMembership: "false",
};

function workspaceTeamIndexes(workspace: AgentConfigWorkspace | undefined): AgentTeamIndexGroup[] {
  const rawIndexes = (workspace as AgentConfigWorkspaceWithTeamIndexes | undefined)?.teamIndexes;
  const indexes = Array.isArray(rawIndexes) ? rawIndexes : [];
  return indexes.filter(
    (item): item is AgentTeamIndexGroup =>
      Boolean(
        item &&
          (item.section === "team_index" || item.section === "source_scope") &&
          item.id &&
          item.label &&
          Array.isArray(item.agentIds),
      ),
  );
}

function teamIndexesWithoutAgentIds(
  workspace: AgentConfigWorkspace | undefined,
  removedAgentIds: Set<string>,
): AgentTeamIndexGroup[] | undefined {
  const indexes = workspaceTeamIndexes(workspace);
  if (!indexes.length) {
    return undefined;
  }
  return indexes.map((group) => {
    const agentIds = group.agentIds.filter((id) => !removedAgentIds.has(id));
    return {
      ...group,
      agentIds,
      count: agentIds.length,
    };
  });
}

function removeAgentFromModeBinding(
  binding: AgentModeBindingItem,
  agentId: string,
  options: { preserveExclusion: boolean },
): AgentModeBindingItem {
  const availableAgentIds = (binding.availableAgentIds ?? []).filter((id) => String(id || "").trim() !== agentId);
  const defaultAgentId = String(binding.defaultAgentId || "").trim() === agentId ? "" : binding.defaultAgentId;
  const nextSlots = Object.fromEntries(
    Object.entries(binding.slots ?? {}).map(([slot, value]) => [slot, String(value || "").trim() === agentId ? "" : value]),
  );
  const nextFlowBindings = Object.fromEntries(
    Object.entries(binding.flowBindings ?? {}).filter(([, value]) => String(value || "").trim() !== agentId),
  );
  return {
    ...binding,
    defaultAgentId: defaultAgentId || availableAgentIds[0] || "",
    availableAgentIds,
    pool: (binding.pool ?? []).filter((id) => String(id || "").trim() !== agentId),
    flowBindings: nextFlowBindings,
    slots: nextSlots,
    excludedAgentIds: options.preserveExclusion
      ? Array.from(new Set([...(binding.excludedAgentIds ?? []), agentId]))
      : (binding.excludedAgentIds ?? []).filter((id) => String(id || "").trim() !== agentId),
  };
}

function removeAgentFromModeBindings(
  modeBindings: AgentConfigWorkspace["modeBindings"],
  agentId: string,
  options: { preserveExclusion: boolean },
): AgentConfigWorkspace["modeBindings"] {
  return Object.fromEntries(
    Object.entries(modeBindings ?? {}).map(([mode, binding]) => [
      mode,
      removeAgentFromModeBinding(binding, agentId, options),
    ]),
  );
}

function removeAgentFromChatRooms(
  chatRooms: AgentConfigWorkspace["chatRooms"],
  agentId: string,
  removedRoomIds: Set<string>,
): AgentConfigWorkspace["chatRooms"] {
  return chatRooms.map((room) => {
    if (!removedRoomIds.has(room.roomId) && !room.agentIds.includes(agentId)) {
      return room;
    }
    const nextAgentIds = room.agentIds.filter((id) => id !== agentId);
    return {
      ...room,
      agentIds: nextAgentIds,
      participantCount: Math.max(0, room.participantCount - (room.agentIds.length - nextAgentIds.length)),
    };
  });
}

function directSessionReference(
  agent: AgentConfigWorkspaceAgent | AgentArchiveResponse,
  cachedReferences: AgentConfigReference[] = [],
): AgentConfigReference[] {
  const directSessionId = String(agent.directSessionId || "").trim();
  if (!directSessionId) {
    return [];
  }
  const existingReference = cachedReferences.find(
    (reference) => reference.kind === "direct_session" && reference.sourceId === directSessionId,
  );
  return [
    {
      ...existingReference,
      kind: "direct_session",
      sourceId: directSessionId,
      sourceLabel: String(agent.displayName || directSessionId).trim(),
      mode: "",
      field: "directSessionId",
      route: existingReference?.route || "/chat",
      status: "active",
    },
  ];
}

function archivedReferences(
  cachedAgent: AgentConfigWorkspaceAgent,
  archivedAgent: AgentArchiveResponse,
): AgentConfigReference[] {
  const removedTeamIds = new Set(
    (archivedAgent.archiveSummary?.removedFromTeamIds ?? []).map((id) => String(id || "").trim()).filter(Boolean),
  );
  const preserved = cachedAgent.references
    .filter((reference) => reference.kind === "team" && !removedTeamIds.has(reference.sourceId))
    .map((reference) => ({
      ...reference,
      status: "stale",
    }));
  const directSession = directSessionReference({ ...cachedAgent, ...archivedAgent }, cachedAgent.references);
  return [...directSession, ...preserved];
}

function archivedHealthIssues(agent: AgentConfigWorkspaceAgent, references: AgentConfigReference[]): AgentConfigHealthIssue[] {
  return references
    .filter((reference) => reference.kind === "team")
    .map((reference) => ({
      severity: "warning",
      code: "stale_team_member",
      agentId: agent.agentId,
      agentCode: agent.agentCode,
      title: "团队成员引用了不可用 Agent",
      detail: `${reference.sourceLabel || reference.sourceId || "-"} 中的成员 agentId=${agent.agentId} 不在活跃 Agent 列表中。`,
      source: "team",
      action: "在团队画布中替换或解绑该成员。",
    }));
}

function archiveAgentInWorkspace(
  cachedAgent: AgentConfigWorkspaceAgent,
  archivedAgent: AgentArchiveResponse,
): AgentConfigWorkspaceAgent {
  const references = archivedReferences(cachedAgent, archivedAgent);
  const agent = { ...cachedAgent, ...archivedAgent, status: "archived" };
  return {
    ...agent,
    references,
    health: archivedHealthIssues(agent, references),
    agentBoundary: ARCHIVED_BOUNDARY,
    runtimeStatus: {
      state: "archived",
      label: archivedAgent.runtimeStatus?.label || "Archived",
      reason: archivedAgent.runtimeStatus?.reason || "agent_archived",
      runId: archivedAgent.runtimeStatus?.runId || cachedAgent.runtimeStatus?.runId || "",
      runKind: archivedAgent.runtimeStatus?.runKind || cachedAgent.runtimeStatus?.runKind || "",
      sessionId: archivedAgent.runtimeStatus?.sessionId || cachedAgent.runtimeStatus?.sessionId || cachedAgent.directSessionId || "",
      summary: archivedAgent.runtimeStatus?.summary || "",
      updatedAt: archivedAgent.runtimeStatus?.updatedAt || archivedAgent.updatedAt || cachedAgent.updatedAt || "",
      staleRuntimeRunCount: archivedAgent.runtimeStatus?.staleRuntimeRunCount ?? cachedAgent.runtimeStatus?.staleRuntimeRunCount,
      latestHistoricalRunId: archivedAgent.runtimeStatus?.latestHistoricalRunId ?? cachedAgent.runtimeStatus?.latestHistoricalRunId,
      latestHistoricalSessionId: archivedAgent.runtimeStatus?.latestHistoricalSessionId ?? cachedAgent.runtimeStatus?.latestHistoricalSessionId,
      latestHistoricalUpdatedAt: archivedAgent.runtimeStatus?.latestHistoricalUpdatedAt ?? cachedAgent.runtimeStatus?.latestHistoricalUpdatedAt,
    },
  };
}

function healthCounts(issues: AgentConfigHealthIssue[]) {
  const blocking = issues.filter((issue) => issue.severity === "blocking").length;
  const warning = issues.filter((issue) => issue.severity === "warning").length;
  return {
    blocking,
    warning,
    info: issues.filter((issue) => issue.severity === "info").length,
  };
}

function healthStatus(counts: ReturnType<typeof healthCounts>) {
  return counts.blocking > 0 ? "blocked" : counts.warning > 0 ? "warning" : "ok";
}

function rebuildHealth(
  workspace: AgentConfigWorkspace,
  removedAgentId: string,
  extraIssues: AgentConfigHealthIssue[] = [],
): AgentConfigWorkspace["health"] {
  const issues = [
    ...(workspace.health.issues ?? []).filter((issue) => issue.agentId !== removedAgentId),
    ...extraIssues,
  ];
  const byAgent: Record<string, AgentConfigHealthIssue[]> = {};
  for (const issue of issues) {
    if (!byAgent[issue.agentId]) {
      byAgent[issue.agentId] = [];
    }
    byAgent[issue.agentId].push(issue);
  }
  const counts = healthCounts(issues);
  return {
    status: healthStatus(counts),
    issues,
    counts,
    byAgent,
  };
}

function agentInGroup(agent: AgentConfigWorkspaceAgent, groupId: string) {
  if (groupId === "all") {
    return true;
  }
  const archived = agent.status === "archived";
  if (groupId === "active") {
    return !archived;
  }
  if (groupId === "archived") {
    return archived;
  }
  if (archived) {
    return false;
  }
  if (groupId === "needs_review") {
    return agent.health.some((issue) => issue.severity === "blocking" || issue.severity === "warning");
  }
  if (["work_session", "team_role", "system_role", "service_role"].includes(groupId)) {
    return agent.agentBoundary?.type === groupId;
  }
  if (groupId === "group_chat") {
    return agent.references.some((reference) => reference.kind === "chat_room");
  }
  if (groupId === "team") {
    return agent.references.some((reference) => reference.kind === "team");
  }
  if (agent.primaryMode === groupId) {
    return true;
  }
  return agent.references.some((reference) => reference.mode === groupId);
}

function rebuildGroups(workspace: AgentConfigWorkspace, nextAgents: AgentConfigWorkspaceAgent[]) {
  return workspace.groups.map((group) => {
    const agentIds = nextAgents.filter((agent) => agentInGroup(agent, group.id)).map((agent) => agent.agentId);
    return {
      ...group,
      agentIds,
      count: agentIds.length,
      healthCount: nextAgents.filter(
        (agent) =>
          agentIds.includes(agent.agentId) &&
          agent.health.some((issue) => issue.severity === "blocking" || issue.severity === "warning"),
      ).length,
    };
  });
}

function rebuildSummary(
  workspace: AgentConfigWorkspace,
  nextAgents: AgentConfigWorkspaceAgent[],
  nextGroups: AgentConfigWorkspace["groups"],
  nextHealth: AgentConfigWorkspace["health"],
  nextChatRooms: AgentConfigWorkspace["chatRooms"],
) {
  const activeAgents = nextAgents.filter((agent) => agent.status !== "archived");
  return {
    ...workspace.summary,
    agentCount: nextAgents.length,
    activeAgentCount: activeAgents.length,
    archivedAgentCount: nextAgents.length - activeAgents.length,
    runningAgentCount: activeAgents.filter((agent) => agent.runtimeStatus?.state === "running").length,
    blockedAgentCount: activeAgents.filter((agent) => ["blocked", "failed"].includes(String(agent.runtimeStatus?.state || ""))).length,
    chatRoomCount: nextChatRooms.length,
    groupCount: nextGroups.length,
    healthIssueCount: nextHealth.issues.length,
    blockingIssueCount: nextHealth.counts.blocking,
    warningIssueCount: nextHealth.counts.warning,
    inboxPendingCount: nextAgents.reduce((sum, agent) => sum + (agent.agentInboxPendingCount ?? 0), 0),
  };
}

export function archivedWorkspaceCache(
  workspace: AgentConfigWorkspaceWithTeamIndexes | undefined,
  archivedAgent: AgentArchiveResponse,
): AgentConfigWorkspaceWithTeamIndexes | undefined {
  if (!workspace) {
    return workspace;
  }
  const agentId = String(archivedAgent.agentId || "").trim();
  if (!agentId) {
    return workspace;
  }
  const cachedAgent = workspace.agents.find((agent) => agent.agentId === agentId);
  if (!cachedAgent) {
    return workspace;
  }
  const removedRoomIds = new Set((archivedAgent.archiveSummary?.removedFromRoomIds ?? []).map((id) => String(id || "").trim()));
  const nextModeBindings = removeAgentFromModeBindings(workspace.modeBindings, agentId, { preserveExclusion: true });
  const nextChatRooms = removeAgentFromChatRooms(workspace.chatRooms, agentId, removedRoomIds);
  const nextAgents = workspace.agents.map((agent) =>
    agent.agentId === agentId ? archiveAgentInWorkspace(agent, archivedAgent) : agent,
  );
  const archivedAgentForCache = nextAgents.find((agent) => agent.agentId === agentId);
  const nextReferences = {
    ...workspace.references,
    [agentId]: archivedAgentForCache?.references ?? directSessionReference(archivedAgent),
  };
  const nextHealth = rebuildHealth(workspace, agentId, archivedAgentForCache?.health ?? []);
  const nextGroups = rebuildGroups(workspace, nextAgents);
  const nextTeamIndexes = teamIndexesWithoutAgentIds(workspace, new Set([agentId]));
  const nextWorkspace: AgentConfigWorkspaceWithTeamIndexes = {
    ...workspace,
    agents: nextAgents,
    groups: nextGroups,
    summary: rebuildSummary(workspace, nextAgents, nextGroups, nextHealth, nextChatRooms),
    modeBindings: nextModeBindings,
    chatRooms: nextChatRooms,
    references: nextReferences,
    health: nextHealth,
  };
  if (nextTeamIndexes) {
    nextWorkspace.teamIndexes = nextTeamIndexes;
  }
  return nextWorkspace;
}

export function purgedWorkspaceCache(
  workspace: AgentConfigWorkspaceWithTeamIndexes | undefined,
  purgedAgentId: string,
): AgentConfigWorkspaceWithTeamIndexes | undefined {
  if (!workspace) {
    return workspace;
  }
  const agentId = String(purgedAgentId || "").trim();
  if (!agentId) {
    return workspace;
  }
  const nextModeBindings = removeAgentFromModeBindings(workspace.modeBindings, agentId, { preserveExclusion: false });
  const nextChatRooms = removeAgentFromChatRooms(workspace.chatRooms, agentId, new Set());
  const nextReferences = { ...workspace.references };
  delete nextReferences[agentId];
  const nextAgents = workspace.agents.filter((agent) => agent.agentId !== agentId);
  const nextHealth = rebuildHealth(workspace, agentId);
  const nextGroups = rebuildGroups(workspace, nextAgents);
  const nextTeamIndexes = teamIndexesWithoutAgentIds(workspace, new Set([agentId]));
  const nextWorkspace: AgentConfigWorkspaceWithTeamIndexes = {
    ...workspace,
    agents: nextAgents,
    groups: nextGroups,
    summary: rebuildSummary(workspace, nextAgents, nextGroups, nextHealth, nextChatRooms),
    modeBindings: nextModeBindings,
    chatRooms: nextChatRooms,
    references: nextReferences,
    health: nextHealth,
  };
  if (nextTeamIndexes) {
    nextWorkspace.teamIndexes = nextTeamIndexes;
  }
  return nextWorkspace;
}

export function bulkPurgeWorkspaceCache(
  workspace: AgentConfigWorkspaceWithTeamIndexes | undefined,
  bulkResponse: AgentBulkActionResponse,
): AgentConfigWorkspaceWithTeamIndexes | undefined {
  return bulkResponse.success.reduce(
    (current, item) => purgedWorkspaceCache(current, item.agentId),
    workspace,
  );
}

export function updatedAgentWorkspaceCache(
  workspace: AgentConfigWorkspaceWithTeamIndexes | undefined,
  updatedAgent: Partial<AgentConfigWorkspaceAgent> & Pick<AgentConfigWorkspaceAgent, "agentId"> & {
    archiveSummary?: AgentArchiveResponse["archiveSummary"];
  },
): AgentConfigWorkspaceWithTeamIndexes | undefined {
  if (!workspace) {
    return workspace;
  }
  if (updatedAgent.status === "archived" && updatedAgent.archiveSummary) {
    return archivedWorkspaceCache(workspace, updatedAgent as AgentArchiveResponse);
  }
  const nextAgents = workspace.agents.map((agent) =>
    agent.agentId === updatedAgent.agentId
      ? {
          ...agent,
          ...updatedAgent,
          references: updatedAgent.references ?? agent.references,
          health: updatedAgent.health ?? agent.health,
          runtimeStatus: updatedAgent.runtimeStatus ?? agent.runtimeStatus,
          dialogueModel: updatedAgent.dialogueModel ?? agent.dialogueModel,
          llmBindingModels: updatedAgent.llmBindingModels ?? agent.llmBindingModels,
          promptTemplate: updatedAgent.promptTemplate ?? agent.promptTemplate,
        }
      : agent,
  );
  return {
    ...workspace,
    agents: nextAgents,
  };
}

export function bulkUpdatedAgentWorkspaceCache(
  workspace: AgentConfigWorkspaceWithTeamIndexes | undefined,
  updatedAgents: Array<Partial<AgentConfigWorkspaceAgent> & Pick<AgentConfigWorkspaceAgent, "agentId">>,
): AgentConfigWorkspaceWithTeamIndexes | undefined {
  return updatedAgents.reduce(
    (current, updatedAgent) => updatedAgentWorkspaceCache(current, updatedAgent),
    workspace,
  );
}
