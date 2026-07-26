/**
 * Pure Agents workspace list / lightweight projection helpers (D3).
 */
import type {
  AgentBoundary,
  AgentConfigReference,
  AgentConfigWorkspace,
  AgentConfigWorkspaceAgent,
  AgentConfigWorkspaceGroup,
  AgentInboxMessage,
  AgentRuntimeEvidence,
  AgentRuntimeEvidenceMatch,
  AgentRunHistory,
} from "../../api/types";
import type { AgentActivityTimelineItem } from "../AgentActivityHistoryPanel";
import type {
  AgentConfigWorkspaceWithTeamIndexes,
  AgentTeamIndexGroup,
} from "../agentWorkspaceCache";
import {
  agentSearchText,
  formatTimestamp,
  normalizeText,
  timestampValue,
  type RuntimeFocusEvidenceResult,
} from "./agentRouteListModel";
import { FALLBACK_AGENT_LLM_SLOTS } from "./agentRouteLlmModel";

export const LIGHTWEIGHT_AGENT_CONFIG_STORAGE = {
  agentRegistryPath: "workspace/agents/agents.json",
  modeBindingPath: "workspace/agent_config/mode_bindings.json",
  promptTemplatePath: "workspace/agent_config/prompt_templates.json",
};

function hasActionableHealthIssue(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return Boolean(agent?.health?.some((issue) => issue.severity === "blocking" || issue.severity === "warning"));
}

export function referenceLabel(reference: AgentConfigReference, lang: "zh" | "en") {
  const kind = reference.kind;
  const zh: Record<string, string> = {
    direct_session: "直连会话",
    mode_default: "模式默认",
    mode_available: "模式可选",
    mode_pool: "模式池",
    mode_slot: "角色槽位",
    flow_binding: "流程绑定",
    chat_room: "群聊",
    team: "团队",
  };
  const en: Record<string, string> = {
    direct_session: "Direct session",
    mode_default: "Mode default",
    mode_available: "Mode available",
    mode_pool: "Mode pool",
    mode_slot: "Role slot",
    flow_binding: "Flow binding",
    chat_room: "Group room",
    team: "Team",
  };
  return (lang === "zh" ? zh : en)[kind] ?? kind;
}

export function referenceRoute(reference: AgentConfigReference) {
  const contractRoute = String(reference.projectionEdit?.canonicalEditRoute || reference.sourceRef?.canonicalEditRoute || "").trim();
  if (contractRoute) {
    return contractRoute;
  }
  if (reference.kind === "team" && reference.sourceId) {
    return `/teams?team=${encodeURIComponent(reference.sourceId)}`;
  }
  return reference.route || "";
}

export function compactProjectionRoute(item: { sourceRef?: { canonicalEditRoute?: string }; projectionEdit?: { canonicalEditRoute?: string } }, fallback: string) {
  return String(item.projectionEdit?.canonicalEditRoute || item.sourceRef?.canonicalEditRoute || fallback || "").trim();
}

export function uniqueModes(agent: AgentConfigWorkspaceAgent) {
  return Array.from(
    new Set(
      [agent.primaryMode, ...agent.references.map((item) => item.mode)]
        .map((item) => String(item || "").trim())
        .filter(Boolean),
    ),
  );
}

export function buildActivityTimeline(
  agent: AgentConfigWorkspaceAgent,
  runs: AgentRunHistory | undefined,
  messages: AgentInboxMessage[] | undefined,
  copy: {
    parentRuns: string;
    subAgentRuns: string;
    maxDepth: string;
    inboxTitle: string;
    wakeStatus: string;
    context: string;
  },
  lang: "zh" | "en",
  evidence: AgentRuntimeEvidence | undefined,
): AgentActivityTimelineItem[] {
  const items: AgentActivityTimelineItem[] = [];
  const evidenceMatches = evidence?.matches ?? [];
  const findEvidence = (sessionId: string, runId: string, messageId = "") => {
    const normalizedSession = String(sessionId || "").trim();
    const normalizedRun = String(runId || "").trim();
    const normalizedMessage = String(messageId || "").trim();
    return evidenceMatches.find((item) => {
      const fields = item.matchedFields ?? {};
      return (
        (normalizedRun && Object.values(fields).includes(normalizedRun))
        || (normalizedSession && Object.values(fields).includes(normalizedSession))
        || (normalizedMessage && Object.values(fields).includes(normalizedMessage))
      );
    }) ?? evidenceMatches[0] ?? null;
  };
  for (const run of runs?.runs ?? []) {
    const timestamp = run.updatedAt || run.finishedAt || run.startedAt || "";
    items.push({
      id: `run:${run.runId}`,
      kind: "run",
      title: run.status || run.currentPhase || run.runKind || copy.parentRuns,
      body: run.summary || run.runId || "-",
      meta: `${copy.parentRuns} · ${run.currentPhase || run.sessionId || "-"}`,
      timestamp,
      sessionId: run.sessionId || agent.directSessionId || "",
      messageId: "",
      canOpenLogs: true,
      evidence: findEvidence(run.sessionId || agent.directSessionId || "", run.sourceRunId || run.runId || ""),
    });
  }
  for (const run of runs?.subAgentRuns ?? []) {
    const timestamp = run.updatedAt || run.endedAt || run.createdAt || "";
    items.push({
      id: `sub:${run.runId}`,
      kind: "sub_run",
      title: `${copy.subAgentRuns} · ${run.status || run.currentPhase || run.runKind || "-"}`,
      body: run.summary || run.subRunId || run.runId || "-",
      meta: `${run.contextMode || "-"} · ${copy.maxDepth} ${run.depth}/${run.maxDepth}`,
      timestamp,
      sessionId: run.parentSessionId || agent.directSessionId || "",
      messageId: "",
      canOpenLogs: true,
      evidence: findEvidence(run.parentSessionId || agent.directSessionId || "", run.runId || run.subRunId || ""),
    });
  }
  for (const message of messages ?? []) {
    const messageId = message.messageId || message.eventId || "";
    items.push({
      id: `inbox:${messageId}`,
      kind: "inbox",
      title: message.sourceAgentName || message.sourceAgentCode || message.sourceAgentId || copy.inboxTitle,
      body: message.summary || message.content || message.threadId || messageId || "-",
      meta: `${copy.inboxTitle} · ${copy.wakeStatus}: ${message.delivery?.wakeStatus || "pending"}`,
      timestamp: message.createdAt || "",
      sessionId: message.targetSessionId || agent.directSessionId || "",
      messageId,
      canOpenLogs: false,
      evidence: findEvidence(message.targetSessionId || agent.directSessionId || "", "", messageId),
    });
  }
  for (const event of agent.groupContextEvents ?? []) {
    items.push({
      id: `context:${event.eventId}`,
      kind: "context",
      title: event.topic || copy.context,
      body: event.summary || event.ownMessage || event.sourceRoomId || "-",
      meta: `${copy.context} · ${event.sourceRoomId || "-"}`,
      timestamp: event.createdAt || "",
      sessionId: event.targetSessionId || agent.directSessionId || "",
      messageId: "",
      canOpenLogs: true,
      evidence: findEvidence(event.targetSessionId || agent.directSessionId || "", event.sourceRoundId || ""),
    });
  }
  return items
    .sort((left, right) => timestampValue(right.timestamp) - timestampValue(left.timestamp))
    .slice(0, 10)
    .map((item) => ({
      ...item,
      meta: `${item.meta} · ${formatTimestamp(item.timestamp, lang)}`,
    }));
}

export function findRuntimeFocusEvidence(
  agent: AgentConfigWorkspaceAgent | null | undefined,
  evidence: AgentRuntimeEvidence | undefined,
): RuntimeFocusEvidenceResult {
  const matches = evidence?.matches ?? [];
  if (!matches.length || !agent?.runtimeStatus) {
    return { match: matches[0] ?? null, reason: matches[0] ? "fallback" : "missing" };
  }
  const runId = String(agent.runtimeStatus.runId || "").trim();
  const sessionId = String(agent.runtimeStatus.sessionId || agent.directSessionId || "").trim();
  const sourceRunId = runId.includes("-") ? runId.split("-").at(-1) ?? "" : "";
  const fieldValues = (item: AgentRuntimeEvidenceMatch) =>
    Object.values(item.matchedFields ?? {}).map((value) => String(value || "").trim());
  const runMatch = matches.find((item) => runId && fieldValues(item).includes(runId));
  if (runMatch) {
    return { match: runMatch, reason: "run" };
  }
  const sourceRunMatch = matches.find((item) => sourceRunId && fieldValues(item).includes(sourceRunId));
  if (sourceRunMatch) {
    return { match: sourceRunMatch, reason: "source_run" };
  }
  const sessionMatch = matches.find((item) => sessionId && fieldValues(item).includes(sessionId));
  if (sessionMatch) {
    return { match: sessionMatch, reason: "session" };
  }
  return { match: matches[0] ?? null, reason: matches[0] ? "fallback" : "missing" };
}

export function workspaceTeamIndexes(workspace: AgentConfigWorkspace | undefined): AgentTeamIndexGroup[] {
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

export function lightweightAgentBoundary(agent: AgentConfigWorkspaceAgent): AgentBoundary {
  if (agent.agentBoundary) {
    return agent.agentBoundary;
  }
  const archived = agent.status === "archived";
  const teamManaged = String(agent.primaryMode || "").trim() === "research";
  return {
    type: archived ? "archived" : teamManaged ? "team_role" : "work_session",
    label: archived ? "已归档 Agent" : teamManaged ? "团队/科研角色 Agent" : "会话入口 Agent",
    ownership: archived ? "archive" : teamManaged ? "team" : "user",
    directSessionRole: agent.directSessionId ? "primary_entry" : "none",
    reason: archived ? "archived" : teamManaged ? "summary_research_mode" : "summary_agent",
    configurationSurface: archived ? "archive" : teamManaged ? "team_role" : "work_session",
    requiresPersonaProfile: teamManaged ? "true" : "false",
    requiresTaskProfile: teamManaged ? "true" : "false",
    requiresTeamMembership: teamManaged ? "true" : "false",
  };
}

export function normalizeLightweightAgent(agent: AgentConfigWorkspaceAgent): AgentConfigWorkspaceAgent {
  const normalized = {
    ...agent,
    references: Array.isArray(agent.references) ? agent.references : [],
    health: Array.isArray(agent.health) ? agent.health : [],
  };
  return {
    ...normalized,
    agentBoundary: lightweightAgentBoundary(normalized),
  };
}

export function lightweightAgentGroup(
  id: string,
  label: string,
  section: string,
  description: string,
  agents: AgentConfigWorkspaceAgent[],
  predicate: (agent: AgentConfigWorkspaceAgent) => boolean,
): AgentConfigWorkspaceGroup {
  const agentIds = agents.filter(predicate).map((agent) => agent.agentId);
  return {
    id,
    label,
    section,
    description,
    agentIds,
    count: agentIds.length,
    healthCount: agents.filter((agent) => agentIds.includes(agent.agentId) && hasActionableHealthIssue(agent)).length,
  };
}

export function buildLightweightAgentWorkspace(
  rawAgents: AgentConfigWorkspaceAgent[],
  updatedAt: number,
): AgentConfigWorkspaceWithTeamIndexes {
  const agents = rawAgents.map(normalizeLightweightAgent);
  const activeAgents = agents.filter((agent) => agent.status !== "archived");
  const issues = agents.flatMap((agent) => agent.health ?? []);
  const groups = [
    lightweightAgentGroup("active", "可用 Agent", "status", "当前可被业务页面引用或调度的 Agent。", agents, (agent) => agent.status !== "archived"),
    lightweightAgentGroup("archived", "已归档", "status", "已封存且不再进入会话栏或可用池，可在 Agent 管理页统一清理。", agents, (agent) => agent.status === "archived"),
    lightweightAgentGroup("chat", "会话模式", "mode", "属于 Chat 运行模式或会话可用池的 Agent。", activeAgents, (agent) => agent.primaryMode === "chat"),
    lightweightAgentGroup("research", "科研模式", "mode", "属于 Research 运行模式或科研池的 Agent。", activeAgents, (agent) => agent.primaryMode === "research"),
    lightweightAgentGroup(
      "supervised_evolution",
      "监督进化模式",
      "mode",
      "占用监督进化模式引用的 Agent。",
      activeAgents,
      (agent) => agent.primaryMode === "supervised_evolution",
    ),
    lightweightAgentGroup("self_evolution", "自进化模式", "mode", "占用自进化模式引用的 Agent。", activeAgents, (agent) => agent.primaryMode === "self_evolution"),
  ].filter((group) => group.count > 0 || group.id === "active" || group.id === "archived");
  return {
    schemaVersion: 1,
    generatedAt: new Date(updatedAt || Date.now()).toISOString(),
    storage: LIGHTWEIGHT_AGENT_CONFIG_STORAGE,
    summary: {
      agentCount: agents.length,
      activeAgentCount: activeAgents.length,
      archivedAgentCount: agents.length - activeAgents.length,
      runningAgentCount: 0,
      blockedAgentCount: 0,
      modeCount: new Set(activeAgents.map((agent) => agent.primaryMode).filter(Boolean)).size,
      chatRoomCount: 0,
      groupCount: groups.length,
      healthIssueCount: issues.length,
      blockingIssueCount: issues.filter((issue) => issue.severity === "blocking").length,
      warningIssueCount: issues.filter((issue) => issue.severity === "warning").length,
      inboxPendingCount: 0,
      teamCount: 0,
    },
    groups,
    teamIndexes: [],
    agents,
    modeBindings: {},
    promptTemplates: [],
    agentLlmSlots: FALLBACK_AGENT_LLM_SLOTS,
    agentModelChoices: [],
    modelOptions: [],
    toolPolicies: [],
    memoryPolicies: [],
    chatRooms: [],
    teams: [],
    references: Object.fromEntries(agents.map((agent) => [agent.agentId, agent.references ?? []])),
    health: {
      status: issues.some((issue) => issue.severity === "blocking") ? "blocked" : issues.some((issue) => issue.severity === "warning") ? "warning" : "ok",
      issues,
      counts: {
        blocking: issues.filter((issue) => issue.severity === "blocking").length,
        warning: issues.filter((issue) => issue.severity === "warning").length,
        info: issues.filter((issue) => issue.severity === "info").length,
      },
      byAgent: Object.fromEntries(agents.map((agent) => [agent.agentId, agent.health ?? []])),
    },
    repairWarnings: {
      modeBindings: [],
      promptTemplates: [],
    },
    diagnostics: {
      source: "agent_summary_fallback",
    },
  };
}

export function filterAgents(
  workspace: AgentConfigWorkspace | undefined,
  activeFilter: string,
  searchText: string,
  options?: {
    managementFilterMatches?: (agent: AgentConfigWorkspaceAgent, activeFilter: string) => boolean;
  },
) {
  const agents = workspace?.agents ?? [];
  const query = normalizeText(searchText);
  const managementFilter = activeFilter.startsWith("setup:");
  const group = (workspace?.groups ?? []).find((item) => item.id === activeFilter);
  const teamIndexGroup = workspaceTeamIndexes(workspace).find((item) => item.id === activeFilter);
  const groupIds = new Set((group ?? teamIndexGroup)?.agentIds ?? []);
  const matchesManagement = options?.managementFilterMatches;
  return agents.filter((agent) => {
    const archived = agent.status === "archived";
    if (activeFilter === "archived") {
      if (!archived) {
        return false;
      }
    } else if (archived) {
      return false;
    }
    if (managementFilter && matchesManagement && !matchesManagement(agent, activeFilter)) {
      return false;
    }
    if (!managementFilter && (group || teamIndexGroup) && !groupIds.has(agent.agentId)) {
      return false;
    }
    return !query || agentSearchText(agent).includes(query);
  });
}

export function selectedAgentFromList(
  agents: AgentConfigWorkspaceAgent[],
  selectedAgentId: string,
  fallbackAgents: AgentConfigWorkspaceAgent[],
  activeFilter: string,
) {
  const fallbackCandidates = activeFilter === "archived"
    ? fallbackAgents.filter((agent) => agent.status === "archived")
    : fallbackAgents.filter((agent) => agent.status !== "archived");
  return (
    agents.find((agent) => agent.agentId === selectedAgentId) ??
    agents[0] ??
    fallbackCandidates[0] ??
    null
  );
}
